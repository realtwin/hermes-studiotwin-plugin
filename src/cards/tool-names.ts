/** Canonical names remain intact (including Concept's studiotwin_ prefix). */
export function cleanToolName(name: string) {
  return name.replace(/^mcp__studiotwin__/, '').replace(/^mcp_studiotwin_/, '').replace(/_/g, '-')
}
export function studiotwinToolAliases(names: readonly string[]) {
  return [...new Set(names.flatMap(name => [
    name,
    `mcp__studiotwin__${name}`,
    `mcp__studiotwin__${name.replace(/-/g, '_')}`,
    `mcp_studiotwin_${name.replace(/-/g, '_')}`,
  ]))]
}
