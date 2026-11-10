from ast import literal_eval
from time import perf_counter

from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline, PipelineConfig, get_llm
from agentdojo.agent_pipeline.basic_elements import InitQuery, SystemMessage
from agentdojo.agent_pipeline.tool_execution import ToolsExecutionLoop, ToolsExecutor, is_string_list
from agentdojo.attacks.attack_registry import load_attack
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.types import ChatToolResultMessage, text_content_block_from_string
from run.data_module import initialize_dataset
from run.eval_support import EvaluationStats, execute_case

from .guard import Decision, Guard, GuardError, Review, write_record


class GuardedToolsExecutor(ToolsExecutor):
    """Intercept a tool call before delegating execution to AgentDojo."""

    def __init__(self, guard: Guard):
        super().__init__()
        self.guard = guard
        self.events = []

    def reset(self):
        self.events.clear()
        self.guard.reset()

    def query(self, query, runtime, env, messages, extra_args):
        if not messages or messages[-1]["role"] != "assistant" or not messages[-1]["tool_calls"]:
            return super().query(query, runtime, env, messages, extra_args)

        pending = messages[-1]
        prefix = list(messages[:-1])
        results = []
        tools = {tool.name: tool for tool in runtime.functions.values()}
        schemas = tuple({
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters.model_json_schema(),
        } for tool in tools.values())

        for call in pending["tool_calls"]:
            if call.function in tools:
                args = {
                    key: literal_eval(value) if isinstance(value, str) and is_string_list(value) else value
                    for key, value in call.args.items()
                }
                call = call.model_copy(update={"args": args})
                verdict = self._review(query, prefix, call, schemas)
            else:
                verdict = Decision.ALLOW  # The original executor reports invalid tools without invoking them.

            proposed = {**pending, "tool_calls": [call]}
            if verdict == Decision.ALLOW:
                _, _, _, executed, _ = super().query(query, runtime, env, [*prefix, proposed], extra_args)
                result = executed[-1]
            else:
                reason = f"Guard decision {verdict.value}. The tool call was not executed."
                result = ChatToolResultMessage(
                    role="tool",
                    content=[text_content_block_from_string(reason)],
                    tool_call_id=call.id,
                    tool_call=call,
                    error=reason,
                )
            prefix.extend((proposed, result))
            results.append(result)

        return query, runtime, env, [*messages, *results], extra_args

    def _review(self, query, prefix, call, schemas):
        started = perf_counter()
        event = {"tool_call_id": call.id, "tool": call.function, "decision": Decision.ERROR}
        try:
            verdict = self.guard.review(Review(tuple(prefix), query, call.model_dump(mode="json"), schemas))
            if verdict.decision == Decision.ERROR:
                raise GuardError("Guard returned ERROR")
            event.update(decision=verdict.decision, risk_score=verdict.risk_score)
            if verdict.details is not None:
                event["details"] = verdict.details
            return verdict.decision
        except GuardError as error:
            event["error"] = str(error)
            raise
        finally:
            event["latency_seconds"] = perf_counter() - started
            self.events.append(event)


def run_agentdojo(args, guard: Guard | None, output):
    config = PipelineConfig(
        llm=args.agent_model,
        provider="openai-compatible",
        defense="ipiguard" if args.method == "ipiguard" else None,
    )
    executor = None
    if guard is None:
        pipeline = AgentPipeline.from_config(config)
    else:
        assert config.system_message is not None
        llm = get_llm("openai-compatible", args.agent_model)
        executor = GuardedToolsExecutor(guard)
        pipeline = AgentPipeline([SystemMessage(config.system_message), InitQuery(), llm,
                                  ToolsExecutionLoop([executor, llm])])
        pipeline.name = args.agent_model

    overall = EvaluationStats()
    total_reviews = 0
    total_review_seconds = 0.0
    for name in args.suite:
        suite = get_suite("v1.2.2", name)
        benign = args.mode == "benign"
        attacker = None if benign else load_attack(args.attack, suite, pipeline)
        excluded = [25] if name == "workspace" else []
        dataset = initialize_dataset(suite, benign=benign, excluded_user_task_ids=excluded)
        pairs = [(i, None) for i in dataset] if benign else dataset
        selected = [
            (uid, iid) for uid, iid in pairs
            if (args.user_task_id is None or uid == args.user_task_id)
            and (args.injection_task_id is None or iid == args.injection_task_id)
        ][:args.limit]
        if not selected:
            raise ValueError(f"No matching cases in suite {name}")
        stats = EvaluationStats()
        review_count = 0
        review_seconds = 0.0
        for uid, iid in selected:
            if executor is not None:
                executor.reset()
            user_task = suite.get_user_task_by_id(f"user_task_{uid}")
            injection_task = suite.get_injection_task_by_id(f"injection_task_{iid}") if iid is not None else None
            injections = attacker.attack(user_task, injection_task) if attacker is not None else {}
            outcome = execute_case(pipeline, suite, user_task, injection_task, injections)
            events = executor.events if executor is not None else []
            if any(event["decision"] == Decision.ERROR for event in events):
                outcome.status = "guard_error"
            for event in events:
                if event["decision"] != Decision.ERROR:
                    review_count += 1
                    review_seconds += event["latency_seconds"]
            stats.add(outcome)
            record = outcome.to_record()
            record.pop("error_message")
            write_record(output, {
                "record_type": "case",
                "suite": name,
                "mode": args.mode,
                "user_task_id": uid,
                "injection_task_id": iid,
                "guard_events": events,
                **record,
            })
        overall.merge(stats)
        total_reviews += review_count
        total_review_seconds += review_seconds
        write_record(output, {
            "record_type": "suite_summary", "suite": name, **stats.to_summary(),
            "successful_reviews": review_count,
            "mean_guard_latency_seconds": review_seconds / review_count if review_count else None,
        })
    summary = {
        "record_type": "overall_summary", **overall.to_summary(),
        "successful_reviews": total_reviews,
        "mean_guard_latency_seconds": total_review_seconds / total_reviews if total_reviews else None,
    }
    write_record(output, summary)
    return summary
