#!/usr/bin/env node
/**
 * Paper search agent using the Claude Agent SDK.
 *
 * Uses @anthropic-ai/claude-agent-sdk to spawn a Claude agent with web search
 * capabilities. Requires ANTHROPIC_API_KEY in the environment.
 *
 * Called by search_papers.py via subprocess:
 *   node search_agent.mjs <prompt_file> <output_file>
 *
 * - Reads the prompt from prompt_file (built by search_papers.py)
 * - Spawns a Claude agent with the prompt
 * - Writes the final text response to output_file
 */

import { query } from "@anthropic-ai/claude-agent-sdk";
import { readFileSync, writeFileSync } from "fs";

const [promptFile, outputFile] = process.argv.slice(2);

if (!promptFile || !outputFile) {
  console.error("Usage: node search_agent.mjs <prompt_file> <output_file>");
  process.exit(1);
}

if (!process.env.ANTHROPIC_API_KEY) {
  console.error(
    "Error: ANTHROPIC_API_KEY not set. Export it before running:\n" +
    "  export ANTHROPIC_API_KEY='sk-ant-...'"
  );
  process.exit(1);
}

const prompt = readFileSync(promptFile, "utf-8");

try {
  const messages = [];

  // query() returns an async iterable of messages
  for await (const message of query({
    prompt,
    options: {
      maxTurns: 15,
      allowedTools: ["WebSearch", "WebFetch", "Read"],
      // Use Claude Code's system prompt for tool access
      systemPrompt: { type: "preset", preset: "claude_code" },
    },
  })) {
    messages.push(message);
  }

  // Extract the final assistant text from the message stream
  const assistantMessages = messages.filter((m) => m.role === "assistant");
  const lastAssistant = assistantMessages[assistantMessages.length - 1];

  let text = "";
  if (lastAssistant && Array.isArray(lastAssistant.content)) {
    text = lastAssistant.content
      .filter((block) => block.type === "text")
      .map((block) => block.text)
      .join("\n");
  } else if (typeof lastAssistant?.content === "string") {
    text = lastAssistant.content;
  }

  writeFileSync(outputFile, text, "utf-8");
  console.error(`Search complete. Output: ${outputFile}`);
} catch (err) {
  console.error(`Search agent error: ${err.message}`);
  writeFileSync(outputFile, JSON.stringify({ error: err.message }), "utf-8");
  process.exit(1);
}
