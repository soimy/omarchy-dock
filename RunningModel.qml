import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons

// Who is running, and which dock item owns them.
//
// Everything v2 does with live windows — the running dot, click-to-focus,
// the unpinned section, pinning, grouping — reduces to one question: which
// toplevels does a dock item match? The answer is keyed on the Wayland
// appId (Hyprland "class"), resolved per item as:
//
//   1. item.appId          explicit override, string or array; wins outright
//   2. entry.startupClass  the desktop entry's StartupWMClass, when set
//   3. webappClass(exec)   Chromium web apps, derived from the launch URL
//   4. the desktop id      the well-behaved case (org.gnome.Nautilus)
//
// Comparison is case-insensitive and also tries the last dot-segment each
// way ("nautilus" vs "org.gnome.Nautilus"), because apps are sloppy here.
//
// The running section is *derived* state: grouped toplevels whose appId no
// pinned item claims. It is never written to shell.json.
Item {
  id: model
  visible: false

  // The plugin root, for desktopEntry() lookups on pinned items.
  required property var dock
  // items[] from shell.json — the pinned half of the dock.
  required property var pinnedItems

  // Apps set their appId a beat after the window maps, and Quickshell's
  // values list doesn't re-notify for it. Bumped by the per-toplevel
  // watchers below so the group binding re-evaluates.
  property int rev: 0

  // Most-recently-used order, newest first, as toplevel references. Closed
  // windows are dropped on the next focus change — the dock stays loaded for
  // the whole session, so an unpruned list only ever grows.
  property var mru: []

  Connections {
    target: ToplevelManager
    function onActiveToplevelChanged() {
      var t = ToplevelManager.activeToplevel
      if (!t) return
      var live = ToplevelManager.toplevels.values || []
      var next = [t]
      for (var i = 0; i < model.mru.length; i++) {
        var w = model.mru[i]
        if (w && w !== t && live.indexOf(w) >= 0) next.push(w)
      }
      model.mru = next
    }
  }

  Instantiator {
    model: ToplevelManager.toplevels.values || []
    delegate: Connections {
      required property var modelData
      target: modelData
      function onAppIdChanged() { model.rev++ }
    }
  }

  // ------------------------------------------------------------- matching

  function canon(s) { return String(s || "").toLowerCase() }
  function tail(s) { var p = canon(s).split("."); return p[p.length - 1] }

  function idMatch(a, b) {
    a = canon(a); b = canon(b)
    if (!a || !b) return false
    return a === b || tail(a) === b || a === tail(b)
  }

  // Chromium web apps are the one case both fallbacks miss. Omarchy's
  // webapp installer writes no StartupWMClass, and the window class looks
  // nothing like the desktop id ("Scribe" vs "chrome-example.com__-Default"),
  // so without this every web app reads as "not running" and each dock click
  // launches another copy. Chromium derives the class from the URL:
  //
  //   chrome-<host>_<path>-<profile directory>
  //
  // with path's illegal characters folded to "_" — so a bare "/" path
  // becomes the "__" seen above. The port is *not* part of it (Chromium uses
  // url.host(), not host:port), which is what makes these near-impossible to
  // hand-write correctly.
  function webappClass(exec) {
    exec = String(exec || "")
    var url = /--app=(?:"([^"]*)"|'([^']*)'|(\S+))/.exec(exec)
      || /omarchy-launch-webapp\s+(?:-\S*\s+)*(?:"([^"]*)"|'([^']*)'|(\S+))/.exec(exec)
    if (!url) return ""
    var parts = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\/([^\/?#]+)([^?#]*)/.exec(url[1] || url[2] || url[3] || "")
    if (!parts) return ""
    var host = parts[1].replace(/^[^@]*@/, "").replace(/:\d+$/, "")
    if (!host) return ""
    var path = (parts[2] || "/").replace(/[\/\\:*?"<>|]/g, "_")
    var profile = /--profile-directory=(?:"([^"]*)"|'([^']*)'|(\S+))/.exec(exec)
    var dir = profile ? (profile[1] || profile[2] || profile[3]) : "Default"
    return "chrome-" + host + "_" + path + "-" + dir
  }

  function matchKeys(item) {
    if (!Util.isPlainObject(item) || item.spacer === true || item.__divider === true) return []
    if (item.appId !== undefined) {
      var raw = Array.isArray(item.appId) ? item.appId : [item.appId]
      var keys = []
      for (var i = 0; i < raw.length; i++) if (raw[i]) keys.push(String(raw[i]))
      return keys
    }
    var out = []
    var entry = dock.desktopEntry(item)
    if (entry && entry.startupClass) out.push(String(entry.startupClass))
    if (entry && entry.execString) {
      var web = webappClass(entry.execString)
      if (web) out.push(web)
    }
    if (item.desktop) out.push(String(item.desktop).replace(/\.desktop$/, ""))
    return out
  }

  // --------------------------------------------------------------- groups

  // appId (canonical) -> [toplevels], in list order. Windows that never
  // report an appId are unidentifiable and skipped.
  readonly property var groups: {
    void model.rev
    var vals = ToplevelManager.toplevels.values || []
    var out = {}
    for (var i = 0; i < vals.length; i++) {
      var id = canon(vals[i].appId)
      if (!id) continue
      if (!out[id]) out[id] = []
      out[id].push(vals[i])
    }
    return out
  }

  // The item's live windows, most-recently-used first.
  function windowsFor(item) {
    var keys = matchKeys(item)
    if (keys.length === 0) return []
    var wins = []
    for (var gid in groups) {
      for (var k = 0; k < keys.length; k++) {
        if (idMatch(keys[k], gid)) { wins = wins.concat(groups[gid]); break }
      }
    }
    if (wins.length < 2) return wins
    var order = model.mru
    wins.sort(function(a, b) {
      var ia = order.indexOf(a), ib = order.indexOf(b)
      return (ia === -1 ? 1e9 : ia) - (ib === -1 ? 1e9 : ib)
    })
    return wins
  }

  // Desktop entry for a bare appId, for the running section's icon and
  // label. heuristicLookup handles the messy real-world cases; the manual
  // scan backstops it with the same canonical compare used everywhere else.
  function entryFor(appId) {
    var e = null
    try { e = DesktopEntries.heuristicLookup(appId) } catch (err) { e = null }
    if (e) return e
    var values = (DesktopEntries.applications && DesktopEntries.applications.values) || []
    for (var i = 0; i < values.length; i++) {
      var id = String(values[i].id || "").replace(/\.desktop$/, "")
      if (idMatch(id, appId)) return values[i]
    }
    return null
  }

  // Running-but-not-pinned, as synthesized dock items. An app with no
  // desktop entry still shows — generic glyph, appId for a label — since
  // "it is running" is the whole point of the section.
  readonly property var extras: {
    var claimedKeys = []
    var list = Array.isArray(pinnedItems) ? pinnedItems : []
    for (var i = 0; i < list.length; i++)
      claimedKeys = claimedKeys.concat(matchKeys(list[i]))

    var out = []
    for (var gid in groups) {
      var claimed = false
      for (var k = 0; k < claimedKeys.length; k++)
        if (idMatch(claimedKeys[k], gid)) { claimed = true; break }
      if (claimed) continue

      var entry = entryFor(gid)
      var item = { __running: true, appId: gid }
      if (entry) {
        item.label = String(entry.name || gid)
        item.__entry = entry
      } else {
        item.label = gid
        item.glyph = "󰣆"
      }
      out.push(item)
    }
    return out
  }
}
