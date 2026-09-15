"""Streamlit UI for the IT Helpdesk Agent. Reuses chat.run_model_tool_loop."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from chat import now_iso, run_model_tool_loop, safe_slug, trim_history, write_transcript
from env_loader import load_lab_env
from providers import make_provider
from tools import load_tool_declarations, to_openai_tools
from versioning import artifact_version_dict, build_artifact_version

ROOT = Path(__file__).resolve().parent
load_lab_env(ROOT)
ARTIFACTS = ROOT / "artifacts"
TRANSCRIPTS = ROOT / "transcripts"


def result_has_error(result: object) -> bool:
    return isinstance(result, dict) and bool(result.get("error"))


def render_rounds(rounds: list) -> None:
    if not rounds:
        st.caption("Không có tool round.")
        return
    for round_record in rounds:
        index = round_record.get("round", "?")
        calls = round_record.get("tool_calls") or []
        results = round_record.get("tool_results") or []
        with st.expander(f"Round {index} — {len(calls)} tool call(s)", expanded=True):
            if not calls:
                st.write("Không gọi tool. Trả lời trực tiếp.")
                if round_record.get("assistant_text"):
                    st.markdown(round_record["assistant_text"])
                continue
            for offset, call in enumerate(calls):
                name = call.get("name", "?")
                args = call.get("args") or {}
                event = results[offset] if offset < len(results) else {}
                result = event.get("result", event)
                st.markdown(f"**Tool:** `{name}`")
                st.markdown("**Tham số (args)**")
                st.json(args)
                st.markdown("**Kết quả / lỗi**")
                if result_has_error(result):
                    st.error(result.get("error") or result)
                    st.json(result)
                else:
                    st.json(result)
                st.divider()


def ensure_session(provider_name: str, version: str, model: str | None) -> None:
    prompt_path = ARTIFACTS / "system_prompt.md"
    tools_path = ARTIFACTS / "tools.yaml"
    artifact = build_artifact_version(version, prompt_path, tools_path)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    transcript_id = f"{safe_slug(version)}_{safe_slug(provider_name)}_ui_{stamp}"
    path = TRANSCRIPTS / f"{transcript_id}.transcript.json"
    st.session_state.ready = True
    st.session_state.provider_name = provider_name
    st.session_state.version = version
    st.session_state.model = model
    st.session_state.system_prompt = prompt_path.read_text(encoding="utf-8")
    st.session_state.openai_tools = to_openai_tools(load_tool_declarations(tools_path))
    st.session_state.provider = make_provider(provider_name)
    st.session_state.artifact = artifact
    st.session_state.history = []
    st.session_state.turns = []
    st.session_state.transcript_path = path
    st.session_state.transcript = {
        "transcript_id": transcript_id,
        **artifact_version_dict(artifact),
        "provider": provider_name,
        "model": model or getattr(st.session_state.provider, "default_model", None),
        "system_prompt": str(prompt_path),
        "tools": str(tools_path),
        "source": "streamlit_ui",
        "history_window": 5,
        "max_tool_rounds": 4,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "turns": [],
    }


st.set_page_config(page_title="Northstar IT Helpdesk", layout="wide")
st.title("Northstar Labs — IT Helpdesk Agent")
st.caption("UI dùng chung `run_model_tool_loop` với CLI. Trace từng bước chọn tool, args, result và artifact version.")

with st.sidebar:
    st.header("Phiên làm việc")
    provider_name = st.selectbox("Provider", ["openai", "openrouter", "anthropic", "gemini"], index=0)
    version = st.text_input("Artifact version", value="v3")
    model = st.text_input("Model (để trống = default)", value="")
    if st.button("Bắt đầu / reset", type="primary"):
        try:
            ensure_session(provider_name, version.strip() or "v3", model.strip() or None)
            st.success("Session sẵn sàng.")
        except Exception as exc:
            st.session_state.ready = False
            st.error(f"{type(exc).__name__}: {exc}")

    if st.session_state.get("ready"):
        art = st.session_state.artifact
        st.subheader("Artifact version")
        st.code(art.artifact_version, language=None)
        st.caption(f"prompt_hash `{art.prompt_hash[:12]}`")
        st.caption(f"tools_hash `{art.tools_hash[:12]}`")
        st.caption(f"provider `{st.session_state.provider_name}`")
        st.caption(f"transcript `{st.session_state.transcript_path.name}`")

if not st.session_state.get("ready"):
    st.info("Chọn provider rồi bấm **Bắt đầu / reset**. Cần API key trong `.env` khớp provider.")
    st.stop()

left, right = st.columns([1.15, 1])

with left:
    st.subheader("Hội thoại")
    for turn in st.session_state.turns:
        with st.chat_message("user"):
            st.markdown(turn["user"])
        with st.chat_message("assistant"):
            st.markdown(turn.get("assistant_text") or "")
            st.caption(f"status = `{turn.get('status')}` · rounds = {len(turn.get('rounds') or [])}")

    user_text = st.chat_input("Nhập yêu cầu IT helpdesk…")

with right:
    st.subheader("Tool trace")
    if not st.session_state.turns:
        st.caption("Gửi một câu hỏi để xem tool name, args và result theo từng round.")
    else:
        latest = st.session_state.turns[-1]
        st.markdown(f"**User request:** {latest['user']}")
        st.markdown(f"**Status:** `{latest.get('status')}`")
        render_rounds(latest.get("rounds") or [])
        if latest.get("error"):
            st.error(latest["error"])

if user_text:
    messages = [
        {"role": "system", "content": st.session_state.system_prompt},
        *trim_history(st.session_state.history, 5),
        {"role": "user", "content": user_text},
    ]
    turn = {
        "turn_index": len(st.session_state.transcript["turns"]) + 1,
        "started_at": now_iso(),
        "user": user_text,
        "status": "started",
        "assistant_text": None,
        "rounds": [],
        "tool_events": [],
    }
    try:
        result = run_model_tool_loop(
            provider=st.session_state.provider,
            messages=messages,
            tools=st.session_state.openai_tools,
            model=st.session_state.model,
            max_tool_rounds=4,
        )
        turn.update(result)
        st.session_state.history.append({"role": "user", "content": user_text})
        st.session_state.history.append({"role": "assistant", "content": result.get("assistant_text") or ""})
    except Exception as exc:
        turn.update({
            "status": "provider_error",
            "error": f"{type(exc).__name__}: {exc}",
            "assistant_text": f"Lỗi provider: {exc}",
        })
    turn["ended_at"] = now_iso()
    st.session_state.transcript["turns"].append(turn)
    st.session_state.turns.append(turn)
    write_transcript(st.session_state.transcript_path, st.session_state.transcript)
    st.rerun()
