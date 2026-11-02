/**
 * Host half of the Xiaomi-OCR-0 bundle.
 *
 * All the work happens in the MCP row this bundle's patch inserts: the Harness
 * spawns ../mcp_server.py (stdio) and bridges its tools. This module only has to
 * exist so the bundle itself can mount and appear in the Plugins page.
 */
export function apply() {}
