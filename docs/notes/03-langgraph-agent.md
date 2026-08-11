# 03 - LangGraph Agent (The Brain with a Safety Net)

## What It Is

LangGraph is a library for building stateful, multi-step LLM applications as **graphs**. Each step is a **node**, and the flow between steps is controlled by **edges** (which can be conditional).

In this project, the LangGraph agent is the "brain" — it handles the actual LLM interaction, but with built-in error handling that ensures the user never sees a stack trace.

## Why LangGraph (Not Just a Raw LLM Call)

A raw LLM call:
```python
response = llm.invoke(query)  # What if this fails? Times out? Returns garbage?
```

With LangGraph:
```
Query → [Primary Model Node] 
              |
        Success? → Return
              |
        Failure? → [Retry Node]
                        |
                  Success? → Return
                        |
                  Failure? → [Fallback Model Node]
                                  |
                            Success? → Return
                                  |
                            Failure? → [Error Response Node]
                                        → "Service temporarily unavailable"
```

**The key insight:** Error handling is part of the architecture, not an afterthought wrapped in try/except.

## Core LangGraph Concepts

### State

Every graph has a **state** — a TypedDict or Pydantic model that gets passed between nodes and accumulates information:

```python
from typing import TypedDict, Optional

class AgentState(TypedDict):
    query: str                    # User's question
    response: Optional[str]       # LLM's answer
    model_used: Optional[str]     # Which model answered
    retries: int                  # How many retries attempted
    error: Optional[str]          # Error message if all failed
```

### Nodes

Each node is a function that takes state, does something, and returns updated state:

```python
def call_primary_model(state: AgentState) -> AgentState:
    try:
        response = primary_llm.invoke(state["query"])
        return {**state, "response": response, "model_used": "primary"}
    except Exception as e:
        return {**state, "error": str(e), "retries": state["retries"] + 1}

def call_fallback_model(state: AgentState) -> AgentState:
    try:
        response = fallback_llm.invoke(state["query"])
        return {**state, "response": response, "model_used": "fallback"}
    except Exception as e:
        return {**state, "error": str(e)}

def error_response(state: AgentState) -> AgentState:
    return {**state, "response": "I'm sorry, the service is temporarily unavailable. Please try again."}
```

### Edges (Conditional Routing)

Edges define the flow. Conditional edges let you route based on state:

```python
def should_retry_or_fallback(state: AgentState) -> str:
    if state.get("response"):
        return "done"          # Success — go to end
    elif state["retries"] < 2:
        return "retry"         # Try again
    else:
        return "fallback"      # Give up on primary, try fallback

def should_return_or_error(state: AgentState) -> str:
    if state.get("response"):
        return "done"
    else:
        return "error"         # Both models failed
```

### Building the Graph

```python
from langgraph.graph import StateGraph, END

graph = StateGraph(AgentState)

# Add nodes
graph.add_node("primary", call_primary_model)
graph.add_node("fallback", call_fallback_model)
graph.add_node("error", error_response)

# Add edges
graph.set_entry_point("primary")
graph.add_conditional_edges("primary", should_retry_or_fallback, {
    "done": END,
    "retry": "primary",       # Loop back to retry
    "fallback": "fallback"
})
graph.add_conditional_edges("fallback", should_return_or_error, {
    "done": END,
    "error": "error"
})
graph.add_edge("error", END)

# Compile
agent = graph.compile()
```

### Invoking the Agent

```python
result = agent.invoke({
    "query": "What is RAG?",
    "response": None,
    "model_used": None,
    "retries": 0,
    "error": None,
})

print(result["response"])   # The answer
print(result["model_used"]) # Which model answered
```

## ProductionAgent Class

The course wraps this in a class:

```python
class ProductionAgent:
    def __init__(self, settings):
        self.primary_llm = init_chat_model(settings.primary_model)
        self.fallback_llm = init_chat_model(settings.fallback_model)
        self.graph = self._build_graph()
    
    def _build_graph(self):
        # ... build the state graph as above
        return graph.compile()
    
    async def invoke(self, query: str) -> dict:
        result = await self.graph.ainvoke({
            "query": query,
            "response": None,
            "model_used": None,
            "retries": 0,
            "error": None,
        })
        return result
```

## LangGraph vs Akshat's Approach

**Akshat's code:**
```python
if chat_type == ChatType.GENERAL:
    return await self._handle_general_chat(session, message, user_id)
elif chat_type == ChatType.ANALYTICAL:
    return await self._handle_enhanced_analytical_chat(session, message, user_id)
```

This is raw if/else routing. Adding a new chat type means modifying existing code. Error handling is scattered try/except blocks.

**LangGraph approach:**
- Adding a new chat type = adding a node + edge. Existing nodes untouched.
- Error handling is structural (part of the graph), not bolted on.
- Visually debuggable (LangSmith shows the exact path through the graph).
- Retries and fallbacks are first-class concepts, not nested try/except.

## When to Use LangGraph

**Use LangGraph when:**
- You have multiple steps that depend on each other
- You need conditional routing (different paths based on results)
- Error handling needs to be robust (retries, fallbacks)
- You want observability into which path was taken
- The workflow might grow over time (extensibility)

**Don't use LangGraph when:**
- It's a single LLM call with no branching
- The logic is genuinely simple (one prompt, one response)
- You're prototyping and don't need production reliability yet

## Key Difference: Graphs vs Chains

| | LCEL Chains | LangGraph |
|--|-------------|-----------|
| Flow | Linear (A → B → C) | Graph (branches, loops, conditions) |
| Error handling | Try/except wrappers | Built into graph structure |
| State | Passed through pipe | Explicit TypedDict, accumulates |
| Cycles | Not possible | Supported (retry loops) |
| Debugging | Print intermediate values | LangSmith visualizes full path |
| Use case | Simple RAG pipeline | Agents, multi-step workflows |

## Interview Questions

**Q: What is LangGraph and why did you use it?**
A: LangGraph is a framework for building stateful LLM applications as graphs. We used it because our production agent needs conditional routing (retry vs fallback), cycles (retry loops), and explicit state management. This is hard to do cleanly with LCEL chains which are strictly linear.

**Q: How does your agent handle LLM failures?**
A: The LangGraph agent has a built-in safety net. The primary model node attempts the call. If it fails, a conditional edge routes to a retry (up to N times). If retries exhaust, it routes to a fallback model node. If that also fails, it routes to an error response node that returns a friendly message. The user never sees a stack trace because the error path is part of the graph design, not an afterthought.

**Q: What's the difference between LangGraph and LCEL chains?**
A: LCEL chains are linear — data flows A → B → C with no branching or loops. LangGraph is a directed graph — it supports conditional edges (routing based on state), cycles (retry loops), and explicit state accumulation. We use LCEL for simple retrieval chains within nodes, and LangGraph for the overall agent orchestration.

**Q: How do you add a new capability to the agent?**
A: Add a new node (function) and connect it with edges. For example, adding a "retrieval" step is: add a `retrieve_context` node, add an edge from entry to retrieval, then from retrieval to the primary model. Existing nodes don't change — open/closed principle.

**Q: How do you debug a LangGraph agent?**
A: LangSmith traces the entire graph execution — which nodes were visited, what state looked like at each step, which conditional edge was taken, and where failures occurred. You can see "this request went: primary → retry → fallback → success" vs "primary → success" at a glance.
