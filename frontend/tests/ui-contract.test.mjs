import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/main.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/style.css", import.meta.url), "utf8");

test("sidebar exposes expanded, collapsed, and hidden persisted modes", () => {
  for (const mode of ["expanded", "collapsed", "hidden"]) {
    assert.match(app, new RegExp(`"${mode}"`));
  }
  assert.match(app, /khmerlive_sidebar_mode/);
  assert.match(styles, /\.sidebar-collapsed \.body-layout/);
  assert.match(styles, /\.sidebar-hidden \.sidebar\s*\{[^}]*display:\s*none/s);
});

test("mobile navigation announces and implements drawer behavior", () => {
  assert.match(app, /"Open navigation"/);
  assert.match(app, /"Close navigation"/);
  assert.match(app, /setMobileNav\(false\)/);
  assert.match(styles, /\.app-shell\.nav-open \.sidebar/);
  assert.match(styles, /transform:\s*translateX\(-110%\)/);
  assert.match(styles, /transform:\s*translateX\(0\)/);
});

test("final workspace navigation includes operational pages", () => {
  for (const label of [
    "Dashboard",
    "New Translation",
    "My Jobs",
    "Video Library",
    "Video Results",
    "AI Models",
    "Users & Access",
    "System Health",
  ]) {
    assert.ok(app.includes(label), `missing navigation label: ${label}`);
  }
});
