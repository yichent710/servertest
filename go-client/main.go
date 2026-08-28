package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"
	"sync"
	"time"

	"git.17zjh.com/weserver/common-server/codec"
	"git.17zjh.com/weserver/common-server/conn/inet"
	"git.17zjh.com/weserver/common-server/conn/ws"
	"git.17zjh.com/weserver/common-server/option"
	"git.17zjh.com/weserver/common-server/pb/sessionpb"
	clientlib "git.17zjh.com/zhengzunjie/common-client/client"
	"git.17zjh.com/zhengzunjie/gotool/logx"
	"google.golang.org/protobuf/proto"

	"git.17zjh.com/zhengzunjie/garden/app/Garden/actor"
	"git.17zjh.com/zhengzunjie/garden/app/Garden/actor/act/actDef"
	"git.17zjh.com/zhengzunjie/garden/app/Garden/actor/act/actManager"
	"git.17zjh.com/zhengzunjie/garden/app/Garden/actor/act/actMilestoneV2"
	"git.17zjh.com/zhengzunjie/garden/app/Garden/actor/harvests"
	"git.17zjh.com/zhengzunjie/garden/internal/config/garden"
	pbGardenActor "git.17zjh.com/zhengzunjie/garden/pb/garden/pbGardenActor/pbActor"
	"git.17zjh.com/zhengzunjie/garden/pb/garden/pbGardenClient"
	"git.17zjh.com/zhengzunjie/garden/pb/gate/pbGateClient"
	"git.17zjh.com/zhengzunjie/garden/pkg/bd/bd_ins/all"
	"git.17zjh.com/zhengzunjie/garden/pkg/full_registry"
	"git.17zjh.com/zhengzunjie/garden/pkg/req_rsp"
)

const (
	activityID       = 90001
	harvestTypeID    = int64(3010001)
	activityVaryID   = int64(28)
	expectedAddScore = int32(10)
)

var clientActRegistry = full_registry.NewRegistryWithOption(full_registry.Option[garden.ActivityCategory, actManager.ActImpl, actDef.IAct]{
	ParentCtx: logx.WithField("component", "severtest_act_registry"),
})

type event struct {
	Time    string         `json:"time"`
	Step    string         `json:"step"`
	Status  string         `json:"status"`
	Details map[string]any `json:"details,omitempty"`
}

type report struct {
	RunID      string  `json:"run_id"`
	UID        uint64  `json:"uid"`
	ActivityID int32   `json:"activity_id"`
	TestCase   string  `json:"test_case,omitempty"`
	Status     string  `json:"status"`
	Events     []event `json:"events"`
	Assertions []assertionResult `json:"assertions,omitempty"`
	Summary string `json:"summary,omitempty"`
	FailureAnalysis string `json:"failure_analysis,omitempty"`
}

type testCase struct {
	ID string `json:"id"`
	Name string `json:"name"`
	Preconditions []any `json:"preconditions"`
	Steps []caseStep `json:"steps"`
	Assertions []assertion `json:"assertions"`
}
type caseStep struct { Action string `json:"action"`; Params map[string]any `json:"params"`; SaveAs string `json:"save_as"` }
type assertion struct { Name string `json:"name"`; Metric string `json:"metric"`; Op string `json:"op"`; Expected float64 `json:"expected"` }
type assertionResult struct { Name string `json:"name"`; Metric string `json:"metric"`; Actual float64 `json:"actual"`; Expected float64 `json:"expected"`; Passed bool `json:"passed"`; Error string `json:"error,omitempty"` }

func evaluateAssertions(r *report, path string, metrics map[string]float64) error {
	data, err := os.ReadFile(path); if err != nil { return fmt.Errorf("read test case: %w", err) }
	var tc testCase; if err := json.Unmarshal(data, &tc); err != nil { return fmt.Errorf("parse test case: %w", err) }
	failed := 0
	for _, a := range tc.Assertions {
		actual, ok := metrics[a.Metric]; passed := false; msg := ""
		if !ok { msg = "metric not found" } else { switch strings.ToLower(a.Op) { case "eq": passed = actual == a.Expected; case "ne": passed = actual != a.Expected; case "gt": passed = actual > a.Expected; case "gte": passed = actual >= a.Expected; case "lt": passed = actual < a.Expected; case "lte": passed = actual <= a.Expected; default: msg = "unsupported operator" } }
		if !passed { failed++ }
		r.Assertions = append(r.Assertions, assertionResult{Name:a.Name, Metric:a.Metric, Actual:actual, Expected:a.Expected, Passed:passed, Error:msg})
	}
	if failed > 0 { return fmt.Errorf("%d assertion(s) failed", failed) }; return nil
}

func (r *report) add(step, status string, details map[string]any) {
	r.Events = append(r.Events, event{Time: time.Now().Format(time.RFC3339Nano), Step: step, Status: status, Details: details})
}

type testClient struct {
	uid uint64
	idx uint64
	*clientlib.Client[*req_rsp.ReqCtx, *req_rsp.RspCtx]

	mu      sync.RWMutex
	actorPB *pbGardenActor.Actor
	state   *actor.Actor
	updates chan struct{}
}

func newTestClient(uid uint64, host string, port int) (*testClient, error) {
	c := &testClient{uid: uid, state: &actor.Actor{}, updates: make(chan struct{}, 16)}
	remote := option.NewRemoteOption(false, port, inet.Websocket, host).
		SetWsPath("/ws").
		SetFrameReader(&ws.FrameReader{})
	clientOption := clientlib.NewOption[*req_rsp.ReqCtx, *req_rsp.RspCtx]()
	clientOption.AddDialOptions(remote).
		AddConnectionCallback(c).
		SetDispatcher(c).
		SetReqCoder(req_rsp.NewReqCoder(all.AllMsgBinding, false)).
		SetRspCoder(req_rsp.NewRspCoder(all.AllMsgBinding)).
		SetHeartBeatDuration(10 * time.Second).
		SetHeartBeatFunc(c.heartBeat).
		SetBindFunc(c.bind).
		SetBuildReqFunc(c.buildReq).
		SetRspPostProcessor(c.processMsg).
		SetValidator(c.validate)
	inner, err := clientlib.NewClient[*req_rsp.ReqCtx, *req_rsp.RspCtx](context.Background(), clientOption, remote)
	if err != nil {
		return nil, err
	}
	c.Client = inner
	return c, nil
}

func (c *testClient) OnConnectionStart(inet.PublicConn) {}
func (c *testClient) OnConnectionEnd(inet.PublicConn)   {}

func (c *testClient) heartBeat(inner *clientlib.Client[*req_rsp.ReqCtx, *req_rsp.RspCtx]) {
	inner.CallBodyOnly(&sessionpb.SessionHeartBeatReq{})
}

func (c *testClient) bind(inner *clientlib.Client[*req_rsp.ReqCtx, *req_rsp.RspCtx]) {
	data, _ := json.Marshal(&req_rsp.CtxData{Sid: "severtest-local", Lang: "zh-Hans"})
	if _, err := inner.CallBodyAndWait(&sessionpb.SessionBindReq{Uid: c.uid, Data: string(data)}); err != nil {
		fmt.Fprintf(os.Stderr, "bind failed: %v\n", err)
		return
	}
	if _, err := inner.CallBodyAndWait(&sessionpb.SessionConnectionStartReq{}); err != nil {
		fmt.Fprintf(os.Stderr, "connection start failed: %v\n", err)
	}
}

func (c *testClient) buildReq(message any) *req_rsp.ReqCtx {
	c.idx++
	return &req_rsp.ReqCtx{
		ClientToGateMessage: &pbGateClient.ClientToGateMessage{Header: &pbGateClient.ReqHeader{Index: c.idx}},
		Message:             message.(proto.Message),
	}
}

func (c *testClient) processMsg(rsp *req_rsp.RspCtx, err error) (any, error) {
	if err != nil {
		return nil, err
	}
	if rsp.Header.Code != 0 || rsp.Header.Desc != "" {
		return nil, fmt.Errorf("rsp code=%d desc=%s", rsp.Header.Code, rsp.Header.Desc)
	}
	return rsp.GetMessage(), nil
}

func (c *testClient) validate(req *req_rsp.ReqCtx, rsp *req_rsp.RspCtx) bool {
	return req.Header.Cmd == rsp.Header.Cmd && req.Header.Type == rsp.Header.Type
}

func (c *testClient) DispatchMessage(packet codec.RspPacket, _ inet.Conn) {
	rsp, ok := packet.(*req_rsp.RspCtx)
	if !ok {
		fmt.Fprintf(os.Stderr, "push ignored: unexpected packet type %T\n", packet)
		return
	}
	fmt.Fprintf(os.Stderr, "push received: cmd=%d type=%d message=%T\n", rsp.Header.Cmd, rsp.Header.Type, rsp.GetMessage())
	push, ok := rsp.GetMessage().(*pbGardenClient.FullDataPush)
	if !ok {
		return
	}
	for _, diff := range push.ActorDiffs {
		if diff.Actor == nil || diff.Actor.Uid != c.uid {
			fmt.Fprintf(os.Stderr, "actor diff ignored: actor_nil=%t uid=%d expected_uid=%d\n", diff.Actor == nil, func() uint64 {
				if diff.Actor == nil {
					return 0
				}
				return diff.Actor.Uid
			}(), c.uid)
			continue
		}
		fmt.Fprintf(os.Stderr, "actor diff applying: uid=%d update_type=%s base=%d version=%d\n", diff.Actor.Uid, diff.UpdateType.String(), diff.Actor.ClientBaseVersion, diff.Actor.ClientVersion)
		c.applyActor(diff.Actor, diff.UpdateType)
	}
}

func (c *testClient) applyActor(next *pbGardenActor.Actor, updateType pbGardenClient.FullDataUpdateType) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if updateType == pbGardenClient.FullDataUpdateType_Full {
		c.actorPB = next.CloneVT()
	} else {
		if c.actorPB == nil || c.state.ClientVersion != next.ClientBaseVersion {
			return
		}
		actor.ActorMergeDiffToPb(c.actorPB, next)
		c.actorPB.ClientBaseVersion = next.ClientBaseVersion
		c.actorPB.ClientVersion = next.ClientVersion
	}
	c.state = &actor.Actor{}
	c.state.ParseFromPbV2(c.actorPB)
	c.state.ClientBaseVersion = c.actorPB.ClientBaseVersion
	c.state.ClientVersion = c.actorPB.ClientVersion
	select {
	case c.updates <- struct{}{}:
	default:
	}
}

func (c *testClient) refresh(ctx context.Context) error {
	// Discard notifications already observed by a previous request. The next
	// notification must belong to this FullData refresh, otherwise a stale
	// signal can make assertions race the Actor diff.
	for {
		select {
		case <-c.updates:
			continue
		default:
			goto drained
		}
	}

drained:
	c.mu.RLock()
	version := c.state.ClientVersion
	c.mu.RUnlock()
	if _, err := c.CallBodyAndWait(&pbGardenClient.FullDataReq{CurServerDataVersion: version}); err != nil {
		return err
	}
	select {
	case <-c.updates:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (c *testClient) snapshot() (version int64, score int32, draws int32, final bool, harvestIDs []int64, activityReadable bool, err error) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.actorPB == nil {
		return 0, 0, 0, false, nil, false, fmt.Errorf("actor data not initialized")
	}
	harvestIDs = collectHarvestIDs(c.state)
	full, ok := c.state.ActManager.ActData.Load(activityID)
	if !ok || full == nil {
		return c.state.ClientVersion, 0, 0, false, harvestIDs, false, nil
	}
	// Actor parsing restores FullIns but deliberately leaves RealIns unset.
	// Recover only rebuilds that typed pointer and does not run activity logic.
	if full.Wrapper.RealIns == nil && !clientActRegistry.Recover(&full.Wrapper) {
		return c.state.ClientVersion, 0, 0, false, harvestIDs, false, nil
	}
	milestone, ok := full.Wrapper.RealIns.(*actMilestoneV2.ActMilestoneV2)
	if !ok || milestone == nil {
		return c.state.ClientVersion, 0, 0, false, harvestIDs, false, nil
	}
	return c.state.ClientVersion, milestone.GetCurrentScore(), milestone.GetDrawCount(), milestone.GetFinalRewardClaimed(), harvestIDs, true, nil
}

func collectHarvestIDs(state *actor.Actor) []int64 {
	ids := make([]int64, 0, state.Bag.HarvestNum())
	state.Bag.RangeHarvest(func(id int64, _ *harvests.Harvest) bool {
		ids = append(ids, id)
		return true
	})
	return ids
}

func main() {
	uid := flag.Uint64("uid", 10000912, "local test player UID")
	host := flag.String("host", "host.docker.internal", "Garden websocket host")
	port := flag.Int("port", 27203, "Garden websocket port")
	output := flag.String("output", "/reports/milestone-v2-smoke.json", "JSON report path")
	casePath := flag.String("case", "/cases/milestone-v2-submit.json", "test case definition")
	flag.Parse()

	r := &report{RunID: fmt.Sprintf("milestone-v2-%d", time.Now().UnixMilli()), UID: *uid, ActivityID: activityID, TestCase: *casePath, Status: "FAILED"}
	if err := run(r, *host, *port, *casePath); err != nil {
		r.Summary = "测试失败：" + err.Error()
		r.FailureAnalysis = explainFailure(err.Error())
		r.add("run", "FAILED", map[string]any{"error": err.Error()})
		writeReport(*output, r)
		fmt.Fprintf(os.Stderr, "FAILED: %v\n", err)
		os.Exit(1)
	}
	r.Status = "PASSED"
	writeReport(*output, r)
	fmt.Printf("PASSED report=%s\n", *output)
}

func explainFailure(message string) string {
	switch {
	case strings.Contains(message, "websocket.Dial"):
		return "连接阶段失败：检查 Gate 宿主机映射端口、WebSocket 路径 /ws 和网络可达性。"
	case strings.Contains(message, "load initial actor"):
		return "Actor 加载阶段失败：检查 UID 是否存在、Gate 到 Garden 的 RPC/Redis Stream 是否正常，以及服务端是否出现超时。"
	case strings.Contains(message, "assertion"):
		return "业务断言失败：对照报告中的实际值和期望值，确认需求口径、配置和服务端状态变更。"
	case strings.Contains(message, "submit fruits"):
		return "提交请求失败：检查请求参数、果实归属、活动配置和服务端返回错误码。"
	default:
		return "执行阶段失败：先查看失败步骤的请求结果和 Garden 日志，再按服务端模块定位。"
	}
}

func run(r *report, host string, port int, casePath string) error {
	caseData, err := os.ReadFile(casePath)
	if err != nil { return fmt.Errorf("read test case: %w", err) }
	var tc testCase
	if err := json.Unmarshal(caseData, &tc); err != nil { return fmt.Errorf("parse test case: %w", err) }
	harvestCount := 2
	for _, step := range tc.Steps {
		if step.Action == "give_harvest" {
			if value, ok := step.Params["count"].(float64); ok && value > 0 { harvestCount = int(value) }
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	c, err := newTestClient(r.UID, host, port)
	if err != nil {
		return fmt.Errorf("connect Garden: %w", err)
	}
	defer c.Stop()
	r.add("connect", "PASSED", map[string]any{"host": host, "port": port})

	if err := c.refresh(ctx); err != nil {
		return fmt.Errorf("load initial actor: %w", err)
	}
	beforeVersion, beforeScore, beforeDraws, _, beforeIDs, beforeReadable, err := c.snapshot()
	if err != nil {
		return err
	}
	r.add("initial_state", "PASSED", map[string]any{"score": beforeScore, "draw_count": beforeDraws, "harvest_count": len(beforeIDs), "activity_state_readable": beforeReadable})

	for i := 0; i < harvestCount; i++ {
		if _, err := c.CallBodyAndWait(&pbGardenClient.DebugGiveHarvestReq{HarvestId: harvestTypeID, Weight: 3, VaryList: []int64{activityVaryID}}); err != nil {
			return fmt.Errorf("give harvest %d: %w", i+1, err)
		}
	}
	if err := c.refresh(ctx); err != nil {
		return fmt.Errorf("refresh after give harvest: %w", err)
	}
	_, _, _, _, afterIDs, _, err := c.snapshot()
	if err != nil {
		return err
	}
	newIDs := difference(afterIDs, beforeIDs)
	if len(newIDs) != harvestCount {
		return fmt.Errorf("expected %d new harvests, got %d: %v", harvestCount, len(newIDs), newIDs)
	}
	r.add("give_harvest", "PASSED", map[string]any{"harvest_ids": newIDs, "vary_id": activityVaryID})

	raw, err := c.CallBodyAndWait(&pbGardenClient.SubmitMilestoneV2FruitsReq{ActivityId: activityID, HarvestIds: newIDs})
	if err != nil {
		return fmt.Errorf("submit fruits: %w", err)
	}
	rsp, ok := raw.(*pbGardenClient.SubmitMilestoneV2FruitsRsp)
	if !ok {
		return fmt.Errorf("unexpected submit response %T", raw)
	}
	r.add("submit", "PASSED", map[string]any{
		"submitted_score": rsp.SubmittedScore, "overflow_score": rsp.OverflowScore,
		"earned_vitality": rsp.EarnedVitality, "draw_rewards": rsp.DrawRewards, "final_rewards": rsp.FinalRewards,
	})

	if err := c.refresh(ctx); err != nil {
		return fmt.Errorf("refresh final actor: %w", err)
	}
	version, finalScore, finalDraws, finalClaimed, finalIDs, finalReadable, err := c.snapshot()
	if err != nil {
		return err
	}
	if containsAny(finalIDs, newIDs) {
		return fmt.Errorf("final state mismatch score=%d draws=%d remaining_test_fruits=%v", finalScore, finalDraws, containsAny(finalIDs, newIDs))
	}
	r.add("final_state", "PASSED", map[string]any{
		"actor_version": version, "score": finalScore, "draw_count": finalDraws,
		"final_reward_claimed": finalClaimed, "consumed_harvest_ids": newIDs, "activity_state_readable": finalReadable,
	})
	metrics := map[string]float64{"submit.submitted_score": float64(rsp.SubmittedScore), "submit.overflow_score": float64(rsp.OverflowScore), "submit.earned_vitality": float64(rsp.EarnedVitality), "before.score": float64(beforeScore), "after.score": float64(finalScore), "before.draw_count": float64(beforeDraws), "after.draw_count": float64(finalDraws), "before.actor_version": float64(beforeVersion), "after.actor_version": float64(version), "consumed_fruits": 1}
	if err := evaluateAssertions(r, casePath, metrics); err != nil { return err }
	return nil
}

func difference(values, existing []int64) []int64 {
	seen := make(map[int64]struct{}, len(existing))
	for _, value := range existing {
		seen[value] = struct{}{}
	}
	result := make([]int64, 0)
	for _, value := range values {
		if _, ok := seen[value]; !ok {
			result = append(result, value)
		}
	}
	return result
}

func containsAny(values, targets []int64) bool {
	set := make(map[int64]struct{}, len(values))
	for _, value := range values {
		set[value] = struct{}{}
	}
	for _, target := range targets {
		if _, ok := set[target]; ok {
			return true
		}
	}
	return false
}

func writeReport(path string, r *report) {
	data, _ := json.MarshalIndent(r, "", "  ")
	if err := os.WriteFile(path, append(data, '\n'), 0o644); err != nil {
		fmt.Fprintf(os.Stderr, "write report failed: %v\n", err)
	}
}
