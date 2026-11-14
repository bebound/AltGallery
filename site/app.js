(() => {
  "use strict";

  const RAW_HOST = "https://raw.githubusercontent.com/";
  const RELEASE_DOWNLOAD = /^https:\/\/github\.com\/[^/]+\/[^/]+\/releases\/(?:latest\/)?download\//;
  const DEFAULT_PROXY_PREFIX = "https://gh-proxy.com/";
  const STORE_KEY = { lang: "altgallery.lang", mode: "altgallery.mode" };
  const SVG_NS = "http://www.w3.org/2000/svg";
  const RECENT_LIMIT = 12; // apps in the "recently updated" ring
  const RECENT_SPEED = 34; // px per second the rail drifts while idle
  const RECENT_HOLD_MS = 2600; // pause after a swipe/wheel before drifting again
  const RAIL_GAP = 16; // matches the .track flex gap
  const RAIL_LEAD = 2; // cards kept before the newest app, for backward scrolling
  const RAIL_STEP_SPEED = 1500; // px per second for an arrow-button step
  // The rail drifts toward the left: the cards travel right to left.
  const RECENT_RAIL_DIRECTION = 1;

  // Filled by boot() from all-apps.json; null while the page is loading.
  let data = null;
  let appById = new Map();

  // preview.html inlines the catalog; the deployed page fetches it instead.
  const EMBEDDED = window.__ALTGALLERY_DATA__ || null;

  const state = {
    lang: "en",
    mirror: false,
    query: "",
    sort: "updated",
    modalId: null,
    lastFocus: null,
    lockedY: 0,
    locked: false,
    recentDrawn: false,
    gridDrawn: false
  };

  const STRINGS = {
    en: {
      "lang.label": "Language",
      "mode.label": "Connection",
      "mode.direct": "Direct",
      "mode.mirror": "Mirror",
      "nav.label": "Sections",
      "nav.overview": "Overview",
      "nav.library": "Library",
      "hero.eyebrow": "AltStore sources",
      "hero.sub": "Curated AltStore sources for IPA projects on GitHub.",
      "hero.clients": "Works with AltStore, SideStore, LiveContainer and other compatible clients.",
      "hero.addAll": "Add all sources",
      "hero.repo": "View on GitHub",
      "hero.scroll": "Browse the library",
      "hero.modeDirect": "Links and downloads use github.com directly.",
      "hero.modeMirror": "Links and downloads go through gh-proxy.com.",
      "stats.apps": "{n} apps",
      "stats.updated": "Updated {d}",
      "updates.title": "Recently updated",
      "updates.badge": "New update",
      "rail.prev": "Previous updates",
      "rail.next": "Next updates",
      "search.placeholder": "Search apps, developers or keywords",
      "search.label": "Search apps",
      "apps.collection": "The collection",
      "apps.title": "All apps",
      "apps.sortLabel": "Sort",
      "sort.updated": "Recently updated",
      "sort.name": "Name A–Z",
      "apps.count": "{n} apps",
      "apps.empty": "No apps match your search.",
      "load.loading": "Loading the catalog…",
      "load.error": "Could not load the catalog. Check your connection and reload, or open",
      "card.add": "Add source",
      "card.addShort": "Add",
      "card.open": "View details for {name}",
      "card.version": "v{v}",
      "card.minOS": "iOS {v}+",
      "card.updated": "Updated {d}",
      "card.about": "About",
      "card.screenshots": "Screenshots",
      "card.screenshotAlt": "Screenshot {n}",
      "card.notes": "Release notes",
      "card.github": "GitHub",
      "card.download": "Download IPA",
      "modal.close": "Close",
      "footer.note": "Catalog generated from GitHub Releases with AltGen; sources refresh every 6 hours.",
      "footer.request": "Request an app"
    },
    zh: {
      "lang.label": "语言",
      "mode.label": "连接方式",
      "mode.direct": "直连",
      "mode.mirror": "镜像",
      "nav.label": "页面导航",
      "nav.overview": "概览",
      "nav.library": "应用库",
      "hero.eyebrow": "AltStore 软件源",
      "hero.sub": "精选 AltStore 软件源：汇聚 GitHub 优质 IPA 开源项目",
      "hero.clients": "兼容 AltStore、SideStore、LiveContainer 等客户端。",
      "hero.addAll": "添加全部源",
      "hero.repo": "在 GitHub 查看",
      "hero.scroll": "浏览应用库",
      "hero.modeDirect": "链接和下载直连 GitHub。",
      "hero.modeMirror": "链接和下载经由 gh-proxy.com 镜像。",
      "stats.apps": "{n} 个 App",
      "stats.updated": "更新于 {d}",
      "updates.title": "最近更新",
      "updates.badge": "最近更新",
      "rail.prev": "上一组更新",
      "rail.next": "下一组更新",
      "search.placeholder": "搜索 App、开发者或关键词",
      "search.label": "搜索 App",
      "apps.collection": "精选合集",
      "apps.title": "全部 App",
      "apps.sortLabel": "排序",
      "sort.updated": "最近更新",
      "sort.name": "名称 A–Z",
      "apps.count": "{n} 个 App",
      "apps.empty": "没有匹配的 App。",
      "load.loading": "正在加载目录…",
      "load.error": "无法加载目录，请检查网络后刷新，或直接打开",
      "card.add": "添加源",
      "card.addShort": "添加",
      "card.open": "查看 {name} 详情",
      "card.version": "v{v}",
      "card.minOS": "iOS {v}+",
      "card.updated": "更新于 {d}",
      "card.about": "简介",
      "card.screenshots": "截图",
      "card.screenshotAlt": "截图 {n}",
      "card.notes": "发布说明",
      "card.github": "GitHub",
      "card.download": "下载 IPA",
      "modal.close": "关闭",
      "footer.note": "目录由 AltGen 从 GitHub Releases 生成，每 6 小时更新一次。",
      "footer.request": "请求添加 App"
    }
  };

  function t(key, vars) {
    const table = STRINGS[state.lang] || STRINGS.en;
    let text = table[key] !== undefined ? table[key] : (STRINGS.en[key] || key);
    if (vars) {
      for (const [name, value] of Object.entries(vars)) {
        text = text.replaceAll("{" + name + "}", String(value));
      }
    }
    return text;
  }

  function storeRead(key) {
    try { return window.localStorage.getItem(key); } catch (error) { return null; }
  }
  function storeWrite(key, value) {
    try { window.localStorage.setItem(key, value); } catch (error) { /* private mode */ }
  }

  function reduceMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function h(tag, attrs, ...children) {
    const element = document.createElement(tag);
    if (attrs) {
      for (const [key, value] of Object.entries(attrs)) {
        if (value === undefined || value === null || value === false) continue;
        if (key === "class") element.className = value;
        else if (key === "text") element.textContent = value;
        else if (key === "style") element.style.cssText = value;
        else if (key.startsWith("on") && typeof value === "function") {
          element.addEventListener(key.slice(2).toLowerCase(), value);
        } else {
          element.setAttribute(key, value === true ? "" : value);
        }
      }
    }
    for (const child of children.flat()) {
      if (child === undefined || child === null || child === false) continue;
      element.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return element;
  }

  function svgIcon(pathData, size) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("width", size || 14);
    svg.setAttribute("height", size || 14);
    svg.setAttribute("aria-hidden", "true");
    for (const d of pathData) {
      const path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("d", d);
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "currentColor");
      path.setAttribute("stroke-width", "1.7");
      path.setAttribute("stroke-linecap", "round");
      path.setAttribute("stroke-linejoin", "round");
      svg.append(path);
    }
    return svg;
  }
  const PLUS_ICON = ["M8 3.4v9.2", "M3.4 8h9.2"];
  const CHEV_RIGHT = ["M6.4 3.6 10.8 8l-4.4 4.4"];

  function proxyPrefix() {
    return (data && data.proxyPrefix) || DEFAULT_PROXY_PREFIX;
  }

  function proxyURL(url) {
    if (!state.mirror || !url) return url;
    if (url.startsWith(RAW_HOST) || RELEASE_DOWNLOAD.test(url)) return proxyPrefix() + url;
    return url;
  }

  // The build copies every displayed image into media/ with its repository
  // path unchanged, so a raw URL of this repository maps to the local copy by
  // swapping the prefix. config.json lists both spellings of the raw prefix
  // ("refs/heads/<branch>/" and "<branch>/"); derive them when absent.
  function rawBasesFrom(rawBase) {
    const match = String(rawBase || "").match(
      /^(https:\/\/raw\.githubusercontent\.com\/[^/]+\/[^/]+\/)(?:(?:refs\/heads\/)?([^/]+)\/)$/
    );
    if (!match) return rawBase ? [rawBase] : [];
    return [match[1] + "refs/heads/" + match[2] + "/", match[1] + match[2] + "/"];
  }

  function mediaURL(url) {
    if (!url || !data) return url;
    for (const base of data.rawBases) {
      if (url.startsWith(base)) return data.mediaBase + url.slice(base.length);
    }
    return url;
  }

  // Display images come from the site itself; links keep their GitHub URL
  // (or its mirror).
  function assetURL(url) {
    return proxyURL(mediaURL(url));
  }

  function addSourceLink(url) {
    return "https://altdirect.app/?url=" + encodeURIComponent(url);
  }

  // Mirror subscription points at the prepared *-proxy.json files, whose
  // assets and downloads are already rewritten to gh-proxy.com. Prefixing the
  // plain source instead would leave AltStore fetching GitHub directly.
  function subscribeURL(app) {
    if (!state.mirror) return app.source || data.allSource;
    return proxyPrefix() + (app.sourceProxy || data.allSourceProxy);
  }

  function safeTint(value) {
    return typeof value === "string" && /^#[0-9a-fA-F]{3,8}$/.test(value) ? value : "";
  }

  function tintStyle(value) {
    const tint = safeTint(value);
    return tint ? "--tint:" + tint : "";
  }

  function dateValue(value) {
    if (!value) return null;
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      const parts = value.split("-").map(Number);
      return new Date(parts[0], parts[1] - 1, parts[2]);
    }
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function fmtDate(value) {
    const date = dateValue(value);
    if (!date) return "";
    return new Intl.DateTimeFormat(state.lang === "zh" ? "zh-CN" : "en-US", {
      year: "numeric",
      month: "short",
      day: "numeric"
    }).format(date);
  }

  function fmtSize(bytes) {
    if (!bytes || bytes <= 0) return "";
    const mb = bytes / (1024 * 1024);
    if (mb >= 1) return mb.toFixed(1) + " MB";
    return Math.max(1, Math.round(bytes / 1024)) + " KB";
  }

  function collator() {
    return new Intl.Collator(state.lang === "zh" ? "zh-CN" : "en", { sensitivity: "base", numeric: true });
  }

  function matches(app) {
    const terms = state.query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return true;
    const haystack = [app.name, app.developer, app.subtitle, app.description, app.bundleID]
      .join("\n")
      .toLowerCase();
    return terms.every((term) => haystack.includes(term));
  }

  function visibleApps() {
    const list = data.apps.filter(matches);
    const compare = collator();
    if (state.sort === "name") {
      list.sort((a, b) => compare.compare(a.name, b.name));
    } else {
      list.sort((a, b) => (b.date || "").localeCompare(a.date || "") || compare.compare(a.name, b.name));
    }
    return list;
  }

  const $ = (selector) => document.querySelector(selector);
  const grid = $("#grid");
  const modal = $("#modal");
  const modalPanel = modal.querySelector(".modal-panel");
  const modalBody = $("#modal-body");
  const updatesTrack = $("#updates-track");
  let closeTimer = 0;
  let railFrame = 0;
  let scrollFrame = 0;
  // The recent rail is a ring over every app; only a window of cards lives in
  // the DOM (see layoutRail).
  let railApps = [];
  let railReady = false;
  let railUnitPx = 0;
  let railAutoRaf = 0;
  let railAutoLast = 0;
  let railHoldUntil = 0;
  let railWakeTimer = 0;
  let railResizeTimer = 0;
  let railStep = 0; // px left to travel for an arrow-button step
  let railWrittenLeft = 0;
  let railLastLeft = 0;
  let railRecycling = false;
  let railHover = false;
  let railFocus = false;
  let railInView = true;
  let railKeyboard = false;

  function ensureFavicon() {
    let link = document.querySelector('link[rel="icon"]');
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      document.head.append(link);
    }
    link.href = assetURL(data.icon);
  }

  function applyLabels() {
    document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
    document.title = "AltGallery";

    document.querySelectorAll("[data-i18n]").forEach((element) => {
      element.textContent = t(element.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => {
      element.setAttribute("placeholder", t(element.dataset.i18nPlaceholder));
    });
    document.querySelectorAll("[data-i18n-aria]").forEach((element) => {
      element.setAttribute("aria-label", t(element.dataset.i18nAria));
    });
    document.querySelectorAll("#lang-seg button").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.lang === state.lang));
    });
    document.querySelectorAll("#mode-seg button").forEach((button) => {
      button.setAttribute("aria-pressed", String((button.dataset.mode === "mirror") === state.mirror));
    });
    document.querySelectorAll("#sort-seg button").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.sort === state.sort));
      button.disabled = !data;
    });
    $("#mode-note").textContent = t(state.mirror ? "hero.modeMirror" : "hero.modeDirect");
    if (!data) $("#hero-meta").textContent = t("load.loading");
  }

  function applyData() {
    const parts = [
      t("stats.apps", { n: data.apps.length }),
      data.updated ? t("stats.updated", { d: fmtDate(data.updated) }) : ""
    ].filter(Boolean);
    const metaNodes = [];
    parts.forEach((part, index) => {
      if (index > 0) metaNodes.push(h("span", { class: "sep", text: "·" }));
      metaNodes.push(h("span", { text: part }));
    });
    $("#hero-meta").replaceChildren(...metaNodes);

    $("#brand").href = data.repo || "#";
    $("#repo-btn").href = data.repo || "#";
    $("#brand-mark").src = assetURL(data.icon);
    $("#hero-icon").src = assetURL(data.icon);
    $("#add-all").href = addSourceLink(state.mirror ? proxyPrefix() + data.allSourceProxy : data.allSource);
    $("#add-all").removeAttribute("aria-disabled");
    $("#add-all-icon").replaceChildren(svgIcon(PLUS_ICON, 14));
    $("#footer-source").href = data.allSource;
    $("#footer-source").textContent = "all-apps.json";
    $("#footer-proxy").href = proxyPrefix() + data.allSourceProxy;
    $("#footer-proxy").textContent = "all-apps-proxy.json";

    $("#search").disabled = false;
    grid.setAttribute("aria-busy", "false");

    ensureFavicon();
  }

  function iconTile(app, className) {
    const tile = h("span", { class: "icon-tile " + className, style: tintStyle(app.tint) });
    tile.append(h("span", { class: "icon-letter", "aria-hidden": "true", text: (app.name || "?").slice(0, 1).toUpperCase() }));
    if (app.icon) {
      const icon = h("img", { src: assetURL(app.icon), alt: "", loading: "lazy", decoding: "async" });
      icon.addEventListener("error", () => icon.remove());
      tile.append(icon);
    }
    return tile;
  }

  // The rail renders its own promo tile in markup instead of loading the
  // generated news.png: a pale tint gradient with the two radial glows, the
  // rounded icon with a "NEW UPDATE" badge, and the name + tagline — the same
  // language as tools/render_news.py, but sharp at any size and cheap to load.
  function recentCard(app, index) {
    const tint = tintStyle(app.tint) || tintStyle(data.tint);
    const tintAlt = safeTint(data.tint) ? "--tint-alt:" + safeTint(data.tint) : "";
    const style = [tint, tintAlt, state.recentDrawn ? "" : "--i:" + index].filter(Boolean).join(";");
    const tagline = (app.subtitle || "").trim();
    const meta = [app.version ? t("card.version", { v: app.version }) : "", fmtDate(app.date)].filter(Boolean).join(" · ");

    const promo = h(
      "span",
      { class: "recent-media promo" },
      h(
        "span",
        { class: "promo-left" },
        iconTile(app, "promo-icon"),
        h("span", { class: "promo-badge", text: t("updates.badge") })
      ),
      h(
        "span",
        { class: "promo-copy" },
        h("span", { class: "promo-name", text: app.name }),
        tagline ? h("span", { class: "promo-tagline", text: tagline }) : null
      )
    );

    const chevron = svgIcon(CHEV_RIGHT, 14);
    chevron.classList.add("recent-chev");

    return h(
      "button",
      {
        type: "button",
        class: "recent-card" + (state.recentDrawn ? "" : " enter"),
        style,
        "data-id": app.bundleID,
        "aria-haspopup": "dialog",
        "aria-label": t("card.open", { name: app.name })
      },
      promo,
      h("span", { class: "recent-caption" }, h("span", { class: "recent-meta", text: meta }), chevron)
    );
  }

  function renderRecent() {
    if (!data) return;
    const compare = collator();
    // The ring holds the newest apps; the rail walks it forever.
    railApps = data.apps
      .slice()
      .sort((a, b) => (b.date || "").localeCompare(a.date || "") || compare.compare(a.name, b.name))
      .slice(0, RECENT_LIMIT);
    $("#updates").hidden = railApps.length === 0;
    layoutRail();
    state.recentDrawn = true;
    updateRailButtons();
    wakeRail();
  }

  // A long app name has to stay on one line: shrink it until it fits the
  // promo column instead of wrapping (HermesEnabler, LiveContainer+SideStore).
  function fitPromoNames(cards) {
    for (const card of cards) {
      if (!card.isConnected) continue;
      const name = card.querySelector(".promo-name");
      if (!name) continue;
      name.style.removeProperty("font-size");
      let size = parseFloat(window.getComputedStyle(name).fontSize);
      if (!size) continue;
      // scrollWidth/clientWidth are whole pixels, so one scale can leave a
      // pixel or two over; a second pass settles it.
      for (let pass = 0; pass < 3; pass += 1) {
        name.style.fontSize = size.toFixed(1) + "px";
        const room = name.clientWidth;
        if (!room || name.scrollWidth <= room) break;
        size = Math.max(size * (room / name.scrollWidth) * 0.99, 9);
      }
    }
  }

  // The rail walks a ring over the newest apps, with only a window of
  // cards in the DOM. A card that leaves one edge is re-labelled with the app
  // that comes next (or previous) on the ring and moved to the other edge,
  // while the scroll position shifts by exactly the space it took. Nothing is
  // duplicated, and the strip has no start or end, so it never jumps.
  function railRing(index) {
    const count = railApps.length;
    return ((index % count) + count) % count;
  }

  function railCard(index, position) {
    const ring = railRing(index);
    const card = recentCard(railApps[ring], position);
    card.dataset.ring = String(ring);
    return card;
  }

  function railUnit() {
    const card = updatesTrack.firstElementChild;
    return card ? card.getBoundingClientRect().width + RAIL_GAP : 0;
  }

  function layoutRail() {
    stopRailAuto();
    railReady = false;
    railStep = 0;
    updatesTrack.replaceChildren();
    updatesTrack.classList.remove("loop");
    updatesTrack.scrollLeft = 0;
    railWrittenLeft = 0;
    railLastLeft = 0;
    if (railApps.length < 2 || !updatesTrack.clientWidth) return;

    // Fill until the strip reaches the viewport plus RAIL_LEAD cards of runway
    // on each side, so it can be dragged either way from the first frame. The
    // window starts at app -RAIL_LEAD, which puts the newest app at the left
    // edge once the scroll position moves past the lead.
    const cards = [];
    let index = -RAIL_LEAD;
    while (cards.length < 24) {
      const card = railCard(index, cards.length);
      cards.push(card);
      updatesTrack.append(card);
      index += 1;
      if (cards.length >= RAIL_LEAD + 3 && updatesTrack.scrollWidth >= updatesTrack.clientWidth + railUnit() * (RAIL_LEAD + 2)) break;
    }
    fitPromoNames(cards);
    if (updatesTrack.scrollWidth <= updatesTrack.clientWidth + 4) return;

    railReady = true;
    railUnitPx = railUnit();
    updatesTrack.classList.add("loop");
    updatesTrack.scrollLeft = railUnitPx * RAIL_LEAD;
    railWrittenLeft = updatesTrack.scrollLeft;
    railLastLeft = updatesTrack.scrollLeft;
  }

  // Front card out on the left: re-label it as the app after the last card and
  // move it to the right end, then give the scroll position its width back.
  function recycleForward() {
    // Cheap test before touching layout: the front card cannot be out of sight
    // while less than its own width has been scrolled past.
    if (updatesTrack.scrollLeft + 4 < railUnitPx) return false;
    const card = updatesTrack.firstElementChild;
    const last = updatesTrack.lastElementChild;
    if (!card || !last || card === last) return false;
    const track = updatesTrack.getBoundingClientRect();
    const rect = card.getBoundingClientRect();
    if (rect.right + RAIL_GAP > track.left) return false;
    const shift = rect.width + RAIL_GAP;
    if (card.contains(document.activeElement)) document.activeElement.blur();
    card.remove();
    const added = railCard(Number(last.dataset.ring) + 1, 0);
    updatesTrack.append(added);
    fitPromoNames([added]);
    updatesTrack.scrollLeft = Math.max(updatesTrack.scrollLeft - shift, 0);
    railWrittenLeft = updatesTrack.scrollLeft;
    railLastLeft = updatesTrack.scrollLeft;
    return true;
  }

  // The mirror image: the last card is already past the right edge, so moving
  // it in front as the app before the first card changes nothing on screen.
  function recycleBackward() {
    const card = updatesTrack.lastElementChild;
    const first = updatesTrack.firstElementChild;
    if (!card || !first || card === first) return false;
    const track = updatesTrack.getBoundingClientRect();
    const rect = card.getBoundingClientRect();
    if (rect.left - RAIL_GAP < track.right) return false;
    const shift = rect.width + RAIL_GAP;
    if (card.contains(document.activeElement)) document.activeElement.blur();
    card.remove();
    const added = railCard(Number(first.dataset.ring) - 1, 0);
    updatesTrack.prepend(added);
    fitPromoNames([added]);
    updatesTrack.scrollLeft += shift;
    railWrittenLeft = updatesTrack.scrollLeft;
    railLastLeft = updatesTrack.scrollLeft;
    return true;
  }

  // direction > 0 recycles at the left edge, < 0 keeps a card of runway on the
  // left so a backwards drag never runs out.
  function recycleRail(direction) {
    // Keyboard focus parks the rail, recycling included: otherwise each Tab
    // that scrolls the strip into view would append a new card and the track
    // would never let focus out.
    if (!railReady || railRecycling || railFocus) return;
    railRecycling = true;
    try {
      if (direction > 0) {
        for (let count = 0; count < 4 && recycleForward(); count += 1) {}
      } else if (direction < 0) {
        for (let count = 0; count < 4 && updatesTrack.scrollLeft < railUnitPx; count += 1) {
          if (!recycleBackward()) break;
        }
      }
    } finally {
      railRecycling = false;
    }
  }

  function railAutoAllowed() {
    return (
      railReady &&
      railInView &&
      !railHover &&
      !railFocus &&
      !state.modalId &&
      !document.hidden &&
      !reduceMotion() &&
      performance.now() >= railHoldUntil
    );
  }

  function stopRailAuto() {
    if (railAutoRaf) cancelAnimationFrame(railAutoRaf);
    railAutoRaf = 0;
    railAutoLast = 0;
    clearTimeout(railWakeTimer);
    railWakeTimer = 0;
  }

  function ensureRailTick() {
    if (railAutoRaf) return;
    railAutoLast = 0;
    railAutoRaf = requestAnimationFrame(tickRail);
  }

  function railHoldRemaining() {
    return Math.max(0, railHoldUntil - performance.now());
  }

  // Always re-arm rather than skip when a timer is pending: a hold set while
  // one was waiting must push the wake-up back, not be lost.
  function wakeRail() {
    if (railAutoRaf) return;
    clearTimeout(railWakeTimer);
    const wait = railHoldRemaining();
    railWakeTimer = setTimeout(() => {
      railWakeTimer = 0;
      startRailAuto();
    }, wait > 0 ? wait + 40 : 0);
  }

  function startRailAuto() {
    if (railAutoRaf) return;
    if (!railAutoAllowed()) {
      // Only a hold runs out on its own; pointer, focus, visibility and the
      // sheet each wake the rail when they change.
      if (railHoldRemaining() > 0 && !railHover && !railFocus && railInView && !state.modalId && !document.hidden) wakeRail();
      return;
    }
    railAutoLast = 0;
    railAutoRaf = requestAnimationFrame(tickRail);
  }

  function tickRail(now) {
    railAutoRaf = 0;
    const stepping = railStep !== 0;
    if (!stepping && !railAutoAllowed()) {
      startRailAuto();
      return;
    }
    const elapsed = railAutoLast ? Math.min(now - railAutoLast, 80) : 0;
    railAutoLast = now;
    if (elapsed > 0) {
      let delta;
      if (stepping) {
        // Arrow-button steps run through this same loop, so the window keeps
        // recycling on every frame and a step can never run out of cards.
        const move = Math.min(Math.abs(railStep), (RAIL_STEP_SPEED * elapsed) / 1000) * Math.sign(railStep);
        delta = move;
        railStep = Math.abs(railStep - move) < 0.5 ? 0 : railStep - move;
        if (!railStep) holdRail(600);
      } else {
        delta = (RECENT_RAIL_DIRECTION * RECENT_SPEED * elapsed) / 1000;
      }
      const next = updatesTrack.scrollLeft + delta;
      railWrittenLeft = next;
      railLastLeft = next;
      updatesTrack.scrollLeft = next;
      recycleRail(delta > 0 ? 1 : -1);
    }
    if (railStep !== 0 || railAutoAllowed()) railAutoRaf = requestAnimationFrame(tickRail);
    else wakeRail();
  }

  // User input parks the marquee for a moment so it does not fight a swipe,
  // and cancels a step it interrupts.
  function holdRail(ms) {
    railStep = 0;
    railHoldUntil = Math.max(railHoldUntil, performance.now() + ms);
    wakeRail();
  }

  function updateRailButtons() {
    // A ring is never at an end, and it is clipped on both sides.
    const looping = railReady;
    const max = updatesTrack.scrollWidth - updatesTrack.clientWidth;
    const atStart = !looping && updatesTrack.scrollLeft <= 4;
    const atEnd = !looping && (max <= 4 || updatesTrack.scrollLeft >= max - 4);
    $("#rail-prev").disabled = atStart;
    $("#rail-next").disabled = atEnd;
    // Fade the edge that is clipped, so a half-visible card reads as "scroll
    // for more" instead of a layout mistake; drop the fade at either end.
    updatesTrack.classList.toggle("at-start", atStart);
    updatesTrack.classList.toggle("at-end", atEnd);
    updatesTrack.classList.toggle("loop", looping);
  }

  function scrollRail(direction) {
    const unit = railUnitPx || updatesTrack.clientWidth * 0.8;
    const step = Math.max(unit, 160) * direction;
    if (reduceMotion()) {
      const next = updatesTrack.scrollLeft + step;
      railWrittenLeft = next;
      railLastLeft = next;
      updatesTrack.scrollLeft = next;
      recycleRail(direction);
      return;
    }
    railStep += step;
    ensureRailTick();
  }

  function appendInline(parent, text) {
    const pattern = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|\*\*([^*]+)\*\*|`([^`]+)`|(https?:\/\/[^\s<>()]+)/g;
    let last = 0;
    let match;
    while ((match = pattern.exec(text)) !== null) {
      if (match.index > last) parent.append(text.slice(last, match.index));
      if (match[1] !== undefined) {
        parent.append(h("a", { href: match[2], target: "_blank", rel: "noopener", text: match[1] }));
      } else if (match[3] !== undefined) {
        parent.append(h("strong", { text: match[3] }));
      } else if (match[4] !== undefined) {
        parent.append(h("code", { text: match[4] }));
      } else if (match[5] !== undefined) {
        const url = match[5].replace(/[.,;:!?]+$/, "");
        parent.append(h("a", { href: url, target: "_blank", rel: "noopener", text: url }));
      }
      last = pattern.lastIndex;
    }
    if (last < text.length) parent.append(text.slice(last));
  }

  // Minimal Markdown for release notes: headings, lists, links, bold, code,
  // fenced blocks and tables reduced to plain rows. Built from DOM nodes, so
  // nothing in the source text can inject markup.
  function markdown(text) {
    const root = h("div", { class: "md" });
    const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
    let paragraph = [];
    let list = null;
    let listType = "";
    let codeLines = null;

    const flushParagraph = () => {
      if (!paragraph.length) return;
      const node = h("p");
      appendInline(node, paragraph.join(" ").trim());
      root.append(node);
      paragraph = [];
    };
    const flushList = () => {
      if (list) root.append(list);
      list = null;
      listType = "";
    };

    for (const rawLine of lines) {
      const line = rawLine.replace(/\s+$/, "");
      if (codeLines !== null) {
        if (/^\s*```/.test(line)) {
          root.append(h("pre", null, h("code", { text: codeLines.join("\n") })));
          codeLines = null;
        } else {
          codeLines.push(line);
        }
        continue;
      }
      if (/^\s*```/.test(line)) {
        flushParagraph();
        flushList();
        codeLines = [];
        continue;
      }
      if (!line.trim()) {
        flushParagraph();
        flushList();
        continue;
      }
      const heading = /^\s*#{1,6}\s+(.*)$/.exec(line);
      if (heading) {
        flushParagraph();
        flushList();
        const title = h("p", { class: "md-title" });
        appendInline(title, heading[1].replace(/\s*#+\s*$/, ""));
        root.append(title);
        continue;
      }
      if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        flushParagraph();
        flushList();
        root.append(h("hr"));
        continue;
      }
      const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
      const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
      if (bullet || numbered) {
        flushParagraph();
        const type = bullet ? "ul" : "ol";
        if (listType !== type) {
          flushList();
          list = h(type);
          listType = type;
        }
        const item = h("li");
        appendInline(item, (bullet || numbered)[1]);
        list.append(item);
        continue;
      }
      if (list && /^\s{2,}\S/.test(line)) {
        const item = list.lastElementChild;
        if (item) {
          item.append(" ");
          appendInline(item, line.trim());
        }
        continue;
      }
      const quote = /^\s*>\s?(.*)$/.exec(line);
      if (quote) {
        flushList();
        paragraph.push(quote[1]);
        continue;
      }
      if (/^\s*\|.*\|\s*$/.test(line)) {
        flushParagraph();
        flushList();
        const cells = line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
        if (cells.every((cell) => /^:?-{2,}:?$/.test(cell))) continue;
        const row = h("p", { class: "md-row" });
        appendInline(row, cells.join("  ·  "));
        root.append(row);
        continue;
      }
      flushList();
      paragraph.push(line.trim());
    }
    if (codeLines !== null) {
      root.append(h("pre", null, h("code", { text: codeLines.join("\n") })));
    }
    flushParagraph();
    flushList();
    return root;
  }

  function screenshotsBlock(app) {
    const list = (app.screenshots || []).slice(0, 20);
    if (!list.length) return null;
    const strip = h("div", { class: "shots" });
    list.forEach((url, index) => {
      const image = h("img", {
        src: assetURL(url),
        alt: t("card.screenshotAlt", { n: index + 1 }),
        loading: "lazy",
        decoding: "async"
      });
      image.addEventListener("error", () => image.remove());
      strip.append(image);
    });
    return h("section", { class: "m-section" }, h("h3", { text: t("card.screenshots") }), strip);
  }

  function appCard(app, index) {
    const tint = tintStyle(app.tint);
    const add = h(
      "a",
      {
        class: "btn-mini",
        href: addSourceLink(subscribeURL(app)),
        target: "_blank",
        rel: "noopener",
        "aria-label": t("card.add") + " — " + app.name
      },
      svgIcon(PLUS_ICON, 12),
      h("span", { text: t("card.addShort") })
    );

    const meta = [];
    if (app.minOS) meta.push(h("span", { text: t("card.minOS", { v: app.minOS }) }));
    const size = fmtSize(app.size);
    if (size) meta.push(h("span", { text: size }));
    if (app.date) meta.push(h("span", { text: fmtDate(app.date) }));

    const open = h(
      "button",
      {
        type: "button",
        class: "card-open",
        "data-id": app.bundleID,
        "aria-haspopup": "dialog",
        "aria-label": t("card.open", { name: app.name })
      },
      h(
        "span",
        { class: "card-top" },
        iconTile(app, "card-icon"),
        h(
          "span",
          { class: "card-heading" },
          h("span", { class: "card-name", text: app.name }),
          h("span", { class: "card-dev", text: app.developer || " " })
        ),
        h("span", { class: "ver", text: t("card.version", { v: app.version }) })
      ),
      app.subtitle ? h("span", { class: "card-sub", text: app.subtitle }) : null
    );

    return h(
      "article",
      {
        class: "card" + (state.gridDrawn ? "" : " enter"),
        style: [tint, state.gridDrawn ? "" : "--i:" + index].filter(Boolean).join(";"),
        "data-id": app.bundleID
      },
      open,
      h("div", { class: "card-foot" }, h("span", { class: "card-meta" }, ...meta), add)
    );
  }

  function renderApps() {
    if (!data) return;
    const list = visibleApps();
    grid.replaceChildren(...list.map((app, index) => appCard(app, index)));
    $("#apps-count").textContent = t("apps.count", { n: list.length });
    $("#empty").hidden = list.length > 0;
    state.gridDrawn = true;
  }

  function modalActions(app) {
    const actions = h("div", { class: "m-actions" });
    actions.append(
      h(
        "a",
        { class: "btn btn-primary", href: addSourceLink(subscribeURL(app)), target: "_blank", rel: "noopener" },
        svgIcon(PLUS_ICON, 14),
        h("span", { text: t("card.add") })
      )
    );
    if (app.repo) {
      actions.append(h("a", { class: "btn btn-ghost", href: app.repo, target: "_blank", rel: "noopener", text: t("card.github") }));
    }
    if (app.download) {
      actions.append(h("a", { class: "btn btn-ghost", href: proxyURL(app.download), target: "_blank", rel: "noopener", text: t("card.download") }));
    }
    return actions;
  }

  function renderModalBody() {
    const app = state.modalId ? appById.get(state.modalId) : null;
    if (!app) {
      modalBody.replaceChildren();
      return;
    }

    const pills = [];
    if (app.version) pills.push(h("span", { text: t("card.version", { v: app.version }) }));
    if (app.minOS) pills.push(h("span", { text: t("card.minOS", { v: app.minOS }) }));
    const size = fmtSize(app.size);
    if (size) pills.push(h("span", { text: size }));
    if (app.date) pills.push(h("span", { text: t("card.updated", { d: fmtDate(app.date) }) }));

    const head = h(
      "div",
      { class: "m-head", style: tintStyle(app.tint) },
      iconTile(app, "m-icon"),
      h(
        "div",
        { class: "m-titles" },
        h("p", { class: "m-dev", text: app.developer || "AltStore" }),
        h("h2", { class: "m-title", id: "modal-title", text: app.name }),
        app.subtitle ? h("p", { class: "m-sub", text: app.subtitle }) : null,
        pills.length ? h("div", { class: "m-pills" }, ...pills) : null
      )
    );

    const sections = [];
    const shots = screenshotsBlock(app);
    if (shots) sections.push(shots);
    sections.push(
      h("section", { class: "m-section" }, h("h3", { text: t("card.about") }), markdown(app.description || app.subtitle || ""))
    );
    if (app.notes && app.notes !== app.description && app.notes !== app.subtitle) {
      sections.push(
        h(
          "section",
          { class: "m-section m-notes" },
          h("h3", null, t("card.notes"), app.version ? h("span", { text: " · v" + app.version }) : null),
          markdown(app.notes)
        )
      );
    }

    modalBody.replaceChildren(head, modalActions(app), ...sections);
  }

  // The page behind the sheet must not scroll; pin the body at its current
  // offset so closing restores the exact position.
  function lockPage() {
    state.locked = true;
    state.lockedY = window.scrollY || window.pageYOffset || 0;
    document.documentElement.classList.add("is-locked");
    document.body.style.position = "fixed";
    document.body.style.top = -state.lockedY + "px";
    document.body.style.left = "0";
    document.body.style.right = "0";
    document.body.style.width = "100%";
  }

  function unlockPage() {
    state.locked = false;
    document.body.style.position = "";
    document.body.style.top = "";
    document.body.style.left = "";
    document.body.style.right = "";
    document.body.style.width = "";
    window.scrollTo(0, state.lockedY);
    requestAnimationFrame(() => document.documentElement.classList.remove("is-locked"));
  }

  function openModal(id, opener) {
    const app = appById.get(id);
    if (!app) return;
    window.clearTimeout(closeTimer);
    state.modalId = id;
    state.lastFocus = opener || document.activeElement;
    renderModalBody();
    modal.hidden = false;
    modalBody.scrollTop = 0;
    if (!state.locked) lockPage();
    // Force a layout pass so the sheet transitions in from its closed state.
    void modalPanel.offsetHeight;
    requestAnimationFrame(() => {
      modal.classList.add("open");
      modalPanel.focus({ preventScroll: true });
    });
  }

  function closeModal() {
    if (!state.modalId) return;
    state.modalId = null;
    modal.classList.remove("open");
    const finish = () => {
      closeTimer = 0;
      modal.hidden = true;
      modalBody.replaceChildren();
      unlockPage();
      const opener = state.lastFocus;
      state.lastFocus = null;
      if (opener && opener.isConnected && typeof opener.focus === "function") {
        opener.focus({ preventScroll: true });
      }
      wakeRail();
    };
    if (reduceMotion()) finish();
    else closeTimer = window.setTimeout(finish, 360);
  }

  function trapFocus(event) {
    const items = [...modalPanel.querySelectorAll('a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])')]
      .filter((element) => element.getClientRects().length > 0);
    if (!items.length) {
      event.preventDefault();
      modalPanel.focus();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === modalPanel || !modalPanel.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || !modalPanel.contains(active))) {
      event.preventDefault();
      first.focus();
    }
  }

  function prepare(source, config) {
    const rawBase = config.rawBase || deriveRawBase(source.iconURL);
    const rawBases = Array.isArray(config.rawBases) && config.rawBases.length
      ? config.rawBases.slice()
      : rawBasesFrom(rawBase);
    const mediaBase = config.mediaBase || "media/";
    const proxyPrefixValue = config.proxyPrefix || DEFAULT_PROXY_PREFIX;
    const repoParts = rawBase ? rawBase.split("/") : [];
    const repo =
      config.repo ||
      (repoParts.length > 4 ? "https://github.com/" + repoParts[3] + "/" + repoParts[4] : "");
    const allSource = config.allSource || (rawBase ? rawBase + "all-apps.json" : "");
    const allSourceProxy =
      config.allSourceProxy || (rawBase ? rawBase + "all-apps-proxy.json" : "");

    const apps = [];
    for (const app of source.apps || []) {
      const versions = app.versions || [];
      if (!versions.length) continue;
      const latest = versions[0];
      const icon = app.iconURL || "";
      const folderMatch = icon.match(/\/apps\/([^/]+)\//);
      const folder = folderMatch ? decodeURIComponent(folderMatch[1]) : "";
      const download = latest.downloadURL || "";
      const repoMatch = download.match(/^https:\/\/github\.com\/([^/]+\/[^/]+)\//);
      apps.push({
        bundleID: app.bundleIdentifier || app.name || "",
        name: app.name || "",
        developer: app.developerName || "",
        subtitle: app.subtitle || "",
        description: app.localizedDescription || "",
        tint: app.tintColor || "",
        icon,
        screenshots: Array.isArray(app.screenshots) ? app.screenshots.slice() : [],
        version: latest.version || "",
        date: latest.date || "",
        minOS: latest.minOSVersion || "",
        size: latest.size || 0,
        notes: latest.localizedDescription || "",
        download,
        repo: repoMatch ? "https://github.com/" + repoMatch[1] : "",
        source: folder ? rawBase + "apps/" + folder + "/apps.json" : "",
        sourceProxy: folder ? rawBase + "apps/" + folder + "/apps-proxy.json" : ""
      });
    }

    const byId = new Map(apps.map((app) => [app.bundleID, app]));
    const news = (source.news || [])
      .map((item) => {
        const app = byId.get(item.appID) || null;
        return {
          id: item.identifier || item.title || "",
          title: item.title || "",
          caption: item.caption || "",
          date: item.date || "",
          url: item.url || "",
          image: item.imageURL || "",
          tint: item.tintColor || (app ? app.tint : ""),
          appID: item.appID || "",
          app: app ? app.name : ""
        };
      })
      .sort((a, b) => b.date.localeCompare(a.date));

    const dates = apps
      .map((app) => app.date)
      .filter(Boolean)
      .concat(news.map((item) => (item.date || "").slice(0, 10)).filter(Boolean));

    return {
      name: source.name || "AltGallery",
      icon: source.iconURL || "",
      tint: source.tintColor || "",
      rawBases,
      mediaBase,
      proxyPrefix: proxyPrefixValue,
      repo,
      allSource,
      allSourceProxy,
      updated: dates.length ? dates.reduce((max, value) => (value > max ? value : max), dates[0]) : "",
      apps,
      news
    };
  }

  function deriveRawBase(iconURL) {
    const match = String(iconURL || "").match(
      /^(https:\/\/raw\.githubusercontent\.com\/[^/]+\/[^/]+\/(?:refs\/heads\/[^/]+\/|master\/))/
    );
    return match ? match[1] : "";
  }

  async function fetchJSON(url) {
    const response = await fetch(url, { cache: "no-cache" });
    if (!response.ok) throw new Error(url + ": HTTP " + response.status);
    return response.json();
  }

  function skeletonCard() {
    return h(
      "div",
      { class: "card skeleton", "aria-hidden": "true" },
      h(
        "div",
        { class: "card-open" },
        h(
          "div",
          { class: "card-top" },
          h("div", { class: "sk-icon" }),
          h("div", { class: "sk-lines" }, h("div", { class: "sk-line w50" }), h("div", { class: "sk-line w35" }))
        ),
        h("div", { class: "sk-line w90" }),
        h("div", { class: "sk-line w70" })
      )
    );
  }

  function skeletonRecent() {
    return h(
      "div",
      { class: "recent-card skeleton", "aria-hidden": "true" },
      h("div", { class: "recent-media" }),
      h("div", { class: "recent-caption" }, h("div", { class: "sk-line w50" }))
    );
  }

  function renderSkeleton() {
    const cards = [];
    for (let index = 0; index < 6; index += 1) cards.push(skeletonCard());
    grid.replaceChildren(...cards);

    const rail = [];
    for (let index = 0; index < 4; index += 1) rail.push(skeletonRecent());
    updatesTrack.replaceChildren(...rail);
    $("#updates").hidden = false;
  }

  function showError() {
    grid.replaceChildren();
    grid.setAttribute("aria-busy", "false");
    $("#updates").hidden = true;
    const status = $("#status");
    status.replaceChildren(
      document.createTextNode(t("load.error") + " "),
      h("a", { href: "all-apps.json", target: "_blank", rel: "noopener", text: "all-apps.json" })
    );
    status.hidden = false;
  }

  function render() {
    applyLabels();
    if (!data) return;
    applyData();
    renderRecent();
    renderApps();
    if (state.modalId) renderModalBody();
  }

  function initState() {
    const storedLang = storeRead(STORE_KEY.lang);
    if (storedLang === "zh" || storedLang === "en") {
      state.lang = storedLang;
    } else {
      state.lang = String(navigator.language || "en").toLowerCase().startsWith("zh") ? "zh" : "en";
    }
    state.mirror = storeRead(STORE_KEY.mode) === "mirror";
  }

  function watchSections() {
    const links = [...document.querySelectorAll(".nav-links a")];
    if (!links.length || !("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const hash = "#" + entry.target.id;
          for (const link of links) link.classList.toggle("active", link.hash === hash);
        }
      },
      { rootMargin: "-45% 0px -45% 0px", threshold: 0 }
    );
    for (const id of ["overview", "library"]) {
      const section = document.getElementById(id);
      if (section) observer.observe(section);
    }
  }

  function watchReveals() {
    const items = [...document.querySelectorAll("[data-reveal]")];
    if (!items.length) return;
    if (!("IntersectionObserver" in window) || reduceMotion()) {
      items.forEach((item) => item.classList.add("in"));
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.classList.add("in");
          observer.unobserve(entry.target);
        }
      },
      { rootMargin: "0px 0px -6% 0px", threshold: 0.04 }
    );
    items.forEach((item) => observer.observe(item));
  }

  async function boot() {
    applyLabels();
    renderSkeleton();
    try {
      const [source, config] = EMBEDDED
        ? [EMBEDDED.source, EMBEDDED.config || {}]
        : await Promise.all([
            fetchJSON("all-apps.json"),
            fetchJSON("config.json").catch(() => ({}))
          ]);
      data = prepare(source, config);
      appById = new Map(data.apps.map((app) => [app.bundleID, app]));
      render();
    } catch (error) {
      console.error(error);
      showError();
    }
  }

  document.querySelectorAll("#lang-seg button").forEach((button) => {
    button.addEventListener("click", () => {
      state.lang = button.dataset.lang;
      storeWrite(STORE_KEY.lang, state.lang);
      render();
    });
  });

  document.querySelectorAll("#mode-seg button").forEach((button) => {
    button.addEventListener("click", () => {
      state.mirror = button.dataset.mode === "mirror";
      storeWrite(STORE_KEY.mode, state.mirror ? "mirror" : "direct");
      render();
    });
  });

  document.querySelectorAll("#sort-seg button").forEach((button) => {
    button.addEventListener("click", () => {
      if (!data || state.sort === button.dataset.sort) return;
      state.sort = button.dataset.sort;
      applyLabels();
      renderApps();
    });
  });

  $("#search").addEventListener("input", (event) => {
    state.query = event.target.value;
    renderApps();
  });

  grid.addEventListener("click", (event) => {
    const button = event.target.closest(".card-open");
    if (button) openModal(button.dataset.id, button);
  });

  updatesTrack.addEventListener("click", (event) => {
    const card = event.target.closest(".recent-card");
    if (card) openModal(card.dataset.id, card);
  });

  updatesTrack.addEventListener(
    "scroll",
    () => {
      const left = updatesTrack.scrollLeft;
      // A position we did not write ourselves is a swipe, wheel or keyboard
      // scroll: park the marquee briefly and let the user drive.
      if (Math.abs(left - railWrittenLeft) > 2) holdRail(RECENT_HOLD_MS);
      const direction = left > railLastLeft + 0.5 ? 1 : left < railLastLeft - 0.5 ? -1 : 0;
      railLastLeft = left;
      if (direction) recycleRail(direction);
      if (railFrame) return;
      railFrame = requestAnimationFrame(() => {
        railFrame = 0;
        updateRailButtons();
      });
    },
    { passive: true }
  );
  updatesTrack.addEventListener("pointerenter", () => { railHover = true; });
  updatesTrack.addEventListener("pointerleave", () => {
    railHover = false;
    wakeRail();
  });
  updatesTrack.addEventListener("pointerdown", () => holdRail(RECENT_HOLD_MS));
  updatesTrack.addEventListener("wheel", () => holdRail(RECENT_HOLD_MS), { passive: true });
  // Tab focus parks the rail; a card focused by a pointer click, or by the
  // sheet returning focus to its opener, must not freeze it.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Tab") railKeyboard = true;
  }, true);
  document.addEventListener("pointerdown", () => { railKeyboard = false; }, true);
  updatesTrack.addEventListener("focusin", () => { railFocus = railKeyboard; });
  updatesTrack.addEventListener("focusout", (event) => {
    if (event.relatedTarget && updatesTrack.contains(event.relatedTarget)) return;
    railFocus = false;
    wakeRail();
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) wakeRail();
  });
  $("#rail-prev").addEventListener("click", () => scrollRail(-1));
  $("#rail-next").addEventListener("click", () => scrollRail(1));

  // The window of cards depends on the viewport width, so rebuild after a
  // resize.
  window.addEventListener("resize", () => {
    updateRailButtons();
    window.clearTimeout(railResizeTimer);
    railResizeTimer = window.setTimeout(() => {
      layoutRail();
      updateRailButtons();
      wakeRail();
    }, 180);
  });

  // Re-layout when the reduced-motion preference flips while the page is open.
  const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  if (motionQuery.addEventListener) {
    motionQuery.addEventListener("change", () => {
      layoutRail();
      updateRailButtons();
      wakeRail();
    });
  }

  // Only drift while the section is on screen.
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(
      (entries) => {
        railInView = entries[0].isIntersecting;
        if (railInView) wakeRail();
      },
      { threshold: 0.15 }
    ).observe($("#updates"));
  }

  $("#modal-close").addEventListener("click", closeModal);
  modal.addEventListener("click", (event) => {
    if (!event.target.classList.contains("modal-backdrop")) return;
    closeModal();
  });
  document.addEventListener("keydown", (event) => {
    if (!state.modalId) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeModal();
    } else if (event.key === "Tab") {
      trapFocus(event);
    }
  });

  window.addEventListener(
    "scroll",
    () => {
      if (scrollFrame) return;
      scrollFrame = requestAnimationFrame(() => {
        scrollFrame = 0;
        $("#nav").classList.toggle("scrolled", (window.scrollY || 0) > 6);
      });
    },
    { passive: true }
  );

  initState();
  watchSections();
  watchReveals();
  boot();
})();
