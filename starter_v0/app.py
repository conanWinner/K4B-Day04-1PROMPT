"""Streamlit UI for the IT Helpdesk Agent. Reuses chat.run_model_tool_loop.

Ưu tiên hiển thị theo LAB-GUIDE mục 9:
  1. user request
  2. final response
  3. từng tool name và args
  4. tool result / error
  5. round / status
  6. artifact version và hashes
  7. transcript path
"""

from __future__ import annotations

import json
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

STATUS_BADGE = {
    "answered": ("✅", "green"),
    "waiting_for_user": ("⏸️", "orange"),
    "max_tool_rounds": ("⚠️", "orange"),
    "provider_error": ("❌", "red"),
    "started": ("⏳", "blue"),
}


def result_has_error(result: object) -> bool:
    return isinstance(result, dict) and bool(result.get("error"))


def status_badge(status: str) -> str:
    icon, color = STATUS_BADGE.get(status, ("•", "gray"))
    return f":{color}[{icon} {status}]"


def render_tool_trace(rounds: list) -> None:
    """Priority 3, 4, 5 — hiển thị từng tool name, args, result/error, round."""
    if not rounds:
        st.caption("Không có tool round (agent trả lời trực tiếp).")
        return
    for round_record in rounds:
        index = round_record.get("round", "?")
        calls = round_record.get("tool_calls") or []
        results = round_record.get("tool_results") or []
        header = f"Round {index} — {len(calls)} tool call(s)"
        with st.expander(header, expanded=True):
            if not calls:
                st.write("Không gọi tool.")
                continue
            for offset, call in enumerate(calls):
                name = call.get("name", "?")
                args = call.get("args") or {}
                event = results[offset] if offset < len(results) else {}
                result = event.get("result", event)
                is_error = result_has_error(result)
                st.markdown(
                    f"**Tool `#{offset + 1}`:** `{name}` "
                    f"{'· :red[ERROR]' if is_error else '· :green[OK]'}"
                )
                col_a, col_r = st.columns(2)
                with col_a:
                    st.caption("Args")
                    st.json(args)
                with col_r:
                    st.caption("Result / Error")
                    if is_error:
                        msg = result.get("error") if isinstance(result, dict) else str(result)
                        st.error(msg or "unknown error")
                    st.json(result)
                if offset < len(calls) - 1:
                    st.divider()


def render_turn(turn: dict, expanded_trace: bool = True) -> None:
    """Render một turn hoàn chỉnh: 1. user, 2. final response, 3–5. tool trace, status."""
    # Priority 1 — user request
    with st.chat_message("user"):
        st.markdown(turn.get("user", ""))

    # Priority 2 — final response
    with st.chat_message("assistant"):
        text = turn.get("assistant_text") or "_(không có nội dung)_"
        st.markdown(text)

        # Priority 5 — round / status
        status = turn.get("status", "unknown")
        rounds = turn.get("rounds") or []
        cols = st.columns([1, 1, 3])
        cols[0].markdown(f"**Status:** {status_badge(status)}")
        cols[1].markdown(f"**Rounds:** `{len(rounds)}`")
        cols[2].markdown(f"**Turn #:** `{turn.get('turn_index', '?')}`")

        if turn.get("error"):
            st.error(turn["error"])

        # Priority 3, 4, 5 — tool trace theo từng round
        label = f"🔧 Tool trace ({len(rounds)} round(s))"
        with st.expander(label, expanded=expanded_trace):
            render_tool_trace(rounds)


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
st.caption(
    "UI dùng chung `run_model_tool_loop` với CLI. Ưu tiên hiển thị: "
    "user request · final response · tool name/args · result/error · round/status · artifact version · transcript."
)

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
        st.divider()
        st.subheader("Debug")
        with st.expander("System prompt", expanded=False):
            st.code(st.session_state.system_prompt, language="markdown")
        with st.expander("Tool declarations", expanded=False):
            st.json(st.session_state.openai_tools)

if not st.session_state.get("ready"):
    st.info("Chọn provider rồi bấm **Bắt đầu / reset**. Cần API key trong `.env` khớp provider.")
    st.stop()

# ============================================================
# Priority 6 + 7 — Artifact version, hashes và transcript path
# (đặt ở top, luôn thấy được)
# ============================================================
art = st.session_state.artifact
transcript_path: Path = st.session_state.transcript_path

st.subheader("📌 Session metadata")
meta = st.columns([2, 1, 1, 1, 1])
meta[0].markdown(f"**Artifact version**  \n`{art.artifact_version}`")
meta[1].markdown(f"**prompt_hash**  \n`{art.prompt_hash[:12]}`")
meta[2].markdown(f"**tools_hash**  \n`{art.tools_hash[:12]}`")
meta[3].markdown(f"**Provider**  \n`{st.session_state.provider_name}`")
meta[4].markdown(
    f"**Model**  \n`{st.session_state.model or getattr(st.session_state.provider, 'default_model', 'default')}`"
)

with st.expander("📁 Transcript path", expanded=False):
    st.code(str(transcript_path), language=None)
    if transcript_path.exists():
        st.download_button(
            "⬇️ Download transcript JSON",
            data=transcript_path.read_bytes(),
            file_name=transcript_path.name,
            mime="application/json",
        )
    else:
        st.caption("Transcript sẽ được ghi sau turn đầu tiên.")

st.divider()

# ============================================================
# Priority 1–5 — Conversation + tool trace theo từng turn
# ============================================================
st.subheader("💬 Conversation")

if not st.session_state.turns:
    st.caption("Chưa có turn nào. Nhập câu hỏi ở dưới để bắt đầu.")
else:
    last_index = len(st.session_state.turns) - 1
    for idx, turn in enumerate(st.session_state.turns):
        render_turn(turn, expanded_trace=(idx == last_index))
        if idx < last_index:
            st.divider()

user_text = st.chat_input("Nhập yêu cầu IT helpdesk…")

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
