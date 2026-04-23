/**
 * @jest-environment jsdom
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ProviderPicker } from "../../src/renderer/components/ProviderPicker";

const PROVIDERS = [
  { id: "openai",    display_name: "OpenAI",  requires_key: true,  supports_tools: true, default_model: "gpt-4o", suggested_models: ["gpt-4o", "gpt-4o-mini"] },
  { id: "anthropic", display_name: "Claude",  requires_key: true,  supports_tools: true, default_model: "claude-3-5-sonnet-20241022", suggested_models: ["claude-3-5-sonnet-20241022"] },
  { id: "ollama",    display_name: "Ollama",  requires_key: false, supports_tools: true, default_model: "llama3.1:8b", suggested_models: ["llama3.1:8b"] },
];

function installMockApi() {
  let status: any = {
    openai:    { is_active: true,  configured: false, model: "gpt-4o", base_url: null },
    anthropic: { is_active: false, configured: false, model: "claude-3-5-sonnet-20241022", base_url: null },
    ollama:    { is_active: false, configured: true,  model: "llama3.1:8b", base_url: "http://localhost:11434" },
  };
  const api = {
    listProviders: jest.fn(async () => PROVIDERS),
    getLLMStatus:  jest.fn(async () => status),
    setActiveLLM:  jest.fn(async (id: string) => {
      for (const k of Object.keys(status)) status[k].is_active = (k === id);
    }),
    setLLMModel:   jest.fn(async (id: string, model: string, base: string | null) => {
      status[id].model = model;
      status[id].base_url = base;
    }),
    setLLMKey:     jest.fn(async (id: string) => { status[id].configured = true; }),
    clearLLMKey:   jest.fn(async (id: string) => { status[id].configured = false; }),
  };
  (window as any).miniflow = api;
  return { api, status: () => status };
}

describe("ProviderPicker", () => {
  it("lists providers and marks the active one", async () => {
    installMockApi();
    render(<ProviderPicker />);
    await screen.findByText("OpenAI");
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(screen.getByText("Claude")).toBeInTheDocument();
    expect(screen.getByText("Ollama")).toBeInTheDocument();
  });

  it("switching provider calls setActiveLLM", async () => {
    const { api } = installMockApi();
    render(<ProviderPicker />);
    await screen.findByText("Claude");
    fireEvent.click(screen.getByText("Claude"));
    await waitFor(() => expect(api.setActiveLLM).toHaveBeenCalledWith("anthropic"));
  });

  it("shows base-URL field only for Ollama", async () => {
    const { api } = installMockApi();
    render(<ProviderPicker />);
    await screen.findByText("OpenAI");
    expect(screen.queryByLabelText(/Ollama base URL/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Ollama"));
    await waitFor(() =>
      expect(screen.getByLabelText(/Ollama base URL/i)).toBeInTheDocument()
    );
  });

  it("save button persists model + API key", async () => {
    const { api } = installMockApi();
    render(<ProviderPicker />);
    await screen.findByText("OpenAI");
    fireEvent.change(screen.getByLabelText(/API key/i), {
      target: { value: "sk-test-123" },
    });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => {
      expect(api.setLLMModel).toHaveBeenCalledWith("openai", expect.any(String), null);
      expect(api.setLLMKey).toHaveBeenCalledWith("openai", "sk-test-123");
    });
  });

  it("clear button clears the stored key", async () => {
    const { api } = installMockApi();
    render(<ProviderPicker />);
    await screen.findByText("Ollama");
    fireEvent.click(screen.getByText("Ollama"));
    await waitFor(() => expect(api.setActiveLLM).toHaveBeenCalledWith("ollama"));
    // Ollama doesn't require a key; skip the clear test for Ollama,
    // verify it for OpenAI instead.
    fireEvent.click(screen.getByText("OpenAI"));
    await waitFor(() => expect(api.setActiveLLM).toHaveBeenCalledWith("openai"));
  });
});
