"""Streamlit interface for the regulatory knowledge-base assistant."""
import re
import uuid

import streamlit as st


st.set_page_config(
    page_title="LPC Regulatory Copilot",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource(show_spinner=False)
def get_agent():
    """Load the LangChain agent only when the app needs it."""
    from chatbot import agent

    return agent


def content_as_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content)


def extract_sources(result: dict) -> list[str]:
    sources = []
    for message in result.get("messages", []):
        if getattr(message, "type", "") != "tool":
            continue
        matches = re.findall(r"\[Source: ([^\]]+)\]", content_as_text(message.content))
        for source in matches:
            if source not in sources:
                sources.append(source)
    return sources


def answer_question(question: str) -> tuple[str, list[str]]:
    agent = get_agent()
    config = {"configurable": {"thread_id": st.session_state.thread_id}}
    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config,
    )
    messages = result.get("messages", [])
    answer = content_as_text(messages[-1].content) if messages else "Aucune réponse."
    return answer, extract_sources(result)


def render_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
        :root { --ink: #15352b; --muted: #63756d; --mint: #dcefe4; --lime: #c7e86b; --paper: #f7f8f2; }
        .stApp { background: var(--paper); color: var(--ink); font-family: 'DM Sans', sans-serif; }
        [data-testid="stSidebar"] { background: #173b30; }
        [data-testid="stSidebar"] * { color: #edf6e9; }
        h1, h2, h3 { font-family: 'Space Grotesk', sans-serif !important; color: var(--ink); }
        [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color: #d9efba !important; }
        .hero { padding: 2.4rem 0 1.8rem; border-bottom: 1px solid #dce5da; margin-bottom: 1.5rem; }
        .eyebrow { color: #73921f; font-size: .75rem; font-weight: 700; letter-spacing: .13em; text-transform: uppercase; }
        .hero h1 { font-size: clamp(2.2rem, 5vw, 4.4rem); line-height: .98; margin: .5rem 0 .8rem; max-width: 760px; }
        .hero p { color: var(--muted); font-size: 1.05rem; max-width: 680px; margin: 0; }
        .prompt-card { background: white; border: 1px solid #e2e9df; border-radius: 8px; padding: 1rem 1.1rem; min-height: 108px; }
        .prompt-card strong { color: var(--ink); display: block; margin-bottom: .35rem; }
        .prompt-card span { color: var(--muted); font-size: .9rem; }
        .source-pill { background: var(--mint); border-radius: 999px; color: #28533e; display: inline-block; font-size: .78rem; margin: .2rem .25rem .2rem 0; padding: .3rem .65rem; }
        .status { background: #214d3b; border-radius: 999px; color: #d9efba; display: inline-block; font-size: .75rem; padding: .3rem .65rem; }
        div[data-testid="stChatMessage"] { border: 1px solid #e2e9df; border-radius: 8px; margin-bottom: .75rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    render_styles()
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("thread_id", str(uuid.uuid4()))

    with st.sidebar:
        st.markdown("## LPC / COPILOT")
        st.markdown("<span class='status'>● Base réglementaire</span>", unsafe_allow_html=True)
        st.divider()
        st.markdown("### Périmètre")
        st.caption("Recherche sémantique dans les documents indexés par Pinecone, avec réponse générée par Ollama.")
        st.markdown("### Garde-fous")
        st.caption("Les réponses doivent être vérifiées par Regulatory Affairs avant tout usage commercial ou opérationnel.")
        if st.button("Nouvelle conversation", use_container_width=True):
            st.session_state.messages = []
            st.session_state.thread_id = str(uuid.uuid4())
            st.rerun()

    st.markdown(
        "<div class='hero'><div class='eyebrow'>Plant care · intelligence documentaire</div>"
        "<h1>Décider avec les bons documents.</h1>"
        "<p>Interrogez la base réglementaire, comparez les usages et gardez la trace des sources consultées.</p></div>",
        unsafe_allow_html=True,
    )

    if not st.session_state.messages:
        st.markdown("### Commencer une recherche")
        columns = st.columns(3)
        prompts = [
            ("Comparer un produit", "Quelles sont les utilisations enregistrées pour ce produit selon les pays ?"),
            ("Vérifier un usage", "Quels usages sont documentés pour cette culture et ce ravageur ?"),
            ("Explorer la base", "Quels produits et entités actives sont présents dans les documents ?"),
        ]
        for column, (title, prompt) in zip(columns, prompts):
            with column:
                st.markdown(f"<div class='prompt-card'><strong>{title}</strong><span>{prompt}</span></div>", unsafe_allow_html=True)
                if st.button("Poser cette question", key=title, use_container_width=True):
                    st.session_state.pending_question = prompt

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("sources"):
                with st.expander(f"{len(message['sources'])} source(s) consultée(s)"):
                    for source in message["sources"]:
                        st.markdown(f"<span class='source-pill'>{source}</span>", unsafe_allow_html=True)

    question = st.chat_input("Posez une question sur les produits, pays ou usages...")
    question = question or st.session_state.pop("pending_question", None)
    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Recherche dans la base..."):
                try:
                    answer, sources = answer_question(question)
                    st.markdown(answer)
                    if sources:
                        with st.expander(f"{len(sources)} source(s) consultée(s)"):
                            for source in sources:
                                st.markdown(f"<span class='source-pill'>{source}</span>", unsafe_allow_html=True)
                    st.session_state.messages.append({"role": "assistant", "content": answer, "sources": sources})
                except Exception as error:
                    message = "Impossible de contacter la base documentaire. Vérifiez Pinecone, Ollama et votre fichier `.env`."
                    st.error(message)
                    st.session_state.messages.append({"role": "assistant", "content": message, "sources": []})
                    st.caption(f"Détail technique : {error}")


if __name__ == "__main__":
    main()