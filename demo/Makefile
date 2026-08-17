install:        ## uv sync
	uv sync

langgraph:      ## run the LangGraph supervisor demo
	uv run demo_langgraph.py

openai-agents:  ## run the OpenAI Agents SDK demo
	uv run demo_openai_agents.py

anthropic:      ## run the Anthropic orchestrator/worker demo
	uv run demo_anthropic.py

all: langgraph openai-agents anthropic

# Serve one demo over HTTP so Tracely scenarios can drive it. DEMO=langgraph|openai|anthropic.
DEMO ?= langgraph
PORT ?= 8100
serve:          ## serve a demo agent for Tracely scenarios (DEMO=… PORT=…)
	DEMO=$(DEMO) uv run uvicorn server:app --port $(PORT)

