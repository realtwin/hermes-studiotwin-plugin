import * as sdk from "@hermes/plugin-sdk";
import {
  StudioTwinPage,
  type WorkspaceNavigation,
} from "../pages/studiotwin-page.tsx";
import { openSettings, type WorkspaceTab } from "../pages/workspace-data.ts";
import { registerStatusbar } from "./statusbar.tsx";
/** V07 assembly seam: no automatic registration or bundle side effects. */
export function registerWorkspaceAndChrome(ctx: sdk.PluginContext) {
  let selected: WorkspaceTab = "Library";
  const listeners = new Set<(tab: WorkspaceTab) => void>();
  const navigation: WorkspaceNavigation = {
    get: () => selected,
    subscribe(fn) {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
  };
  const revision = sdk.atom(0);
  function WorkspaceRoute() {
    const value = sdk.useValue(revision);
    return <StudioTwinPage key={value} ctx={ctx} navigation={navigation} />;
  }
  const open = (tab: WorkspaceTab = "Library") => {
    selected = tab;
    revision.set(revision.get() + 1);
    listeners.forEach((fn) => fn(tab));
    sdk.host.navigate("/studiotwin");
  };
  ctx.register({
    id: "studiotwin-workspace",
    area: sdk.ROUTES_AREA,
    data: { path: "/studiotwin" },
    render: () => <WorkspaceRoute />,
  });
  ctx.register({
    id: "studiotwin-navigation",
    area: sdk.SIDEBAR_NAV_AREA,
    data: {
      path: "/studiotwin",
      label: "StudioTwin",
      codicon: "sparkle",
    } satisfies sdk.SidebarNavContribution,
  });
  const commands: [string, string, () => void][] = [
    ["workspace", "Open StudioTwin Workspace", () => open()],
    ["library", "StudioTwin: Browse Asset Library", () => open("Library")],
    ["jobs", "StudioTwin: View Active & Past Jobs", () => open("Jobs")],
    ["concepts", "StudioTwin: Open ConceptLab Browser", () => open("Concepts")],
    ["upload", "StudioTwin: Upload Reference Asset", () => open("Upload")],
    [
      "settings",
      "StudioTwin: Configure API Key & Settings",
      () => openSettings(ctx),
    ],
  ];
  for (const [id, label, run] of commands)
    ctx.register({
      id: "studiotwin-" + id + "-command",
      area: sdk.PALETTE_AREA,
      data: {
        id: "studiotwin." + id,
        label,
        keywords: ["studiotwin", id, "assets", "creative"],
        run,
      } satisfies sdk.PaletteContribution,
    });
  registerStatusbar(ctx, open);
  ctx.onDispose(() => listeners.clear());
}
