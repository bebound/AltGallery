(() => {
  "use strict";

  const RAW_HOST = "https://raw.githubusercontent.com/";
  const RELEASE_DOWNLOAD = /^https:\/\/github\.com\/[^/]+\/[^/]+\/releases\/(?:latest\/)?download\//;
  const DEFAULT_PROXY_PREFIX = "https://gh-proxy.com/";
  const STORE_KEY = { lang: "altgallery.lang", mode: "altgallery.mode" };
  const SVG_NS = "http://www.w3.org/2000/svg";
  const RECENT_LIMIT = 12; // apps in the "recently updated" rail
  const RECENT_SPEED = 34; // px per second the rail drifts while idle
  // Auto-scroll's startDelay: how long the drift waits, once the strip has come
  // to rest, before it comes back — after a swipe or a step, and after the rail
  // is un-parked.
  const RECENT_RESTART_MS = 800;
  const RAIL_STEP_DURATION = 25; // Embla's duration unit; the docs recommend 20-60

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
    sheetPushed: false,
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

  // The build copies every displayed image into media/ under its repository
  // path, and records in config.json's mediaFiles the path it actually staged
  // (a WebP re-encode changes the extension). config.json lists both spellings
  // of the raw prefix ("refs/heads/<branch>/" and "<branch>/"); derive them
  // when absent.
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
      if (!url.startsWith(base)) continue;
      let path = url.slice(base.length).split("?")[0];
      try {
        path = decodeURIComponent(path);
      } catch (error) {
        // A path that is not valid percent-encoding is used as written.
      }
      const staged = data.mediaFiles[path] || path;
      return data.mediaBase + staged;
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

  // One date formatter and one collator per language, built on first use.
  // Constructing a DateTimeFormat costs about half a millisecond, and a render
  // asks for one per card: rebuilt per keystroke in the search field, that is
  // tens of milliseconds of nothing but locale setup.
  const intl = { lang: "", date: null, collator: null };

  function intlFor() {
    if (intl.lang !== state.lang) {
      intl.lang = state.lang;
      intl.date = new Intl.DateTimeFormat(state.lang === "zh" ? "zh-CN" : "en-US", {
        year: "numeric",
        month: "short",
        day: "numeric"
      });
      intl.collator = new Intl.Collator(state.lang === "zh" ? "zh-CN" : "en", {
        sensitivity: "base",
        numeric: true
      });
    }
    return intl;
  }

  function fmtDate(value) {
    const date = dateValue(value);
    if (!date) return "";
    return intlFor().date.format(date);
  }

  function fmtSize(bytes) {
    if (!bytes || bytes <= 0) return "";
    const mb = bytes / (1024 * 1024);
    if (mb >= 1) return mb.toFixed(1) + " MB";
    return Math.max(1, Math.round(bytes / 1024)) + " KB";
  }

  function collator() {
    return intlFor().collator;
  }

  // AltStore sources carry one language per app, so the page's Chinese text
  // lives in site/i18n/zh.json, keyed by bundle identifier. An app with no
  // entry keeps its catalog text — the Chinese-only projects already ship
  // theirs in Chinese, and the English projects keep the English original
  // until a translation is added.
  function localizedField(app, field) {
    const table = app.i18n && app.i18n[state.lang];
    const value = table && table[field];
    return (value && String(value).trim()) || app[field] || "";
  }

  function appSubtitle(app) {
    return localizedField(app, "subtitle");
  }

  function appDescription(app) {
    return localizedField(app, "description") || appSubtitle(app);
  }

  function matches(app) {
    const terms = state.query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return true;
    const texts = [app.name, app.developer, app.subtitle, app.description, app.bundleID];
    // Every language is searchable, so a Chinese query finds an English app.
    for (const table of Object.values(app.i18n || {})) {
      texts.push(table.subtitle, table.description);
    }
    const haystack = texts.filter(Boolean).join("\n").toLowerCase();
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
  const railFade = $("#rail-fade");
  let closeTimer = 0;
  let scrollFrame = 0;
  // The recent rail: one card per newest app in a track that Embla keeps in a
  // loop, with the auto-scroll plugin drifting it.
  let railApps = [];
  let railEmbla = null;
  let railAuto = null;
  let railResizeTimer = 0;
  let railHover = false; // a desktop pointer is over the rail
  let railDown = false; // a finger or mouse button is on the strip
  let railInView = true;

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
    const tagline = appSubtitle(app).trim();
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
    // The rail holds the newest apps; Embla walks them in a loop.
    railApps = data.apps
      .slice()
      .sort((a, b) => (b.date || "").localeCompare(a.date || "") || compare.compare(a.name, b.name))
      .slice(0, RECENT_LIMIT);
    $("#updates").hidden = railApps.length === 0;
    layoutRail();
    state.recentDrawn = true;
  }

  // A long app name has to stay on one line: shrink it until it fits the
  // promo column instead of wrapping (HermesEnabler, LiveContainer+SideStore).
  function fitPromoNames(cards) {
    const names = [];
    for (const card of cards) {
      if (!card.isConnected) continue;
      const name = card.querySelector(".promo-name");
      if (!name) continue;
      name.style.removeProperty("font-size");
      names.push(name);
    }
    // Reset every name before reading any of them: a write interleaved with a
    // read would force a layout per card.
    const sizes = names.map((name) => parseFloat(window.getComputedStyle(name).fontSize) || 0);
    names.forEach((name, index) => {
      let size = sizes[index];
      if (!size) return;
      // scrollWidth/clientWidth are whole pixels, so one scale can leave a
      // pixel or two over; a second pass settles it.
      for (let pass = 0; pass < 3; pass += 1) {
        name.style.fontSize = size.toFixed(1) + "px";
        const room = name.clientWidth;
        if (!room || name.scrollWidth <= room) break;
        size = Math.max(size * (room / name.scrollWidth) * 0.99, 9);
      }
    });
  }

  // The rail is a loop over the newest apps: every card lives in the DOM once
  // and Embla translates the strip, so nothing is recycled while it walks. The
  // auto-scroll plugin keeps it drifting, which is what the old hand-written
  // scrollLeft engine existed to do.
  function layoutRail() {
    // The rail is rebuilt to re-label it on a language switch; the reader's
    // place in the strip is worth keeping across that.
    const returnTo = railEmbla
      ? Math.round(railEmbla.scrollProgress() * Math.max(railEmbla.scrollSnapList().length - 1, 0))
      : 0;
    destroyRail();
    updatesTrack.replaceChildren();
    railApps.forEach((app, index) => updatesTrack.append(recentCard(app, index)));
    fitPromoNames([...updatesTrack.children]);
    if (railApps.length < 2) {
      updateRailButtons();
      return;
    }
    // No loop to walk and nothing to drift when the vendored plugin is missing:
    // fall back to the plain scroller the rail started as.
    if (typeof window.EmblaCarousel !== "function" || typeof window.EmblaCarouselAutoScroll !== "function") {
      railFade.classList.add("native");
      updateRailButtons();
      return;
    }
    railAuto = window.EmblaCarouselAutoScroll({
      // Embla steps its engine in fixed 1/60s ticks, so this is pixels per
      // 1/60s however fast the display refreshes.
      speed: RECENT_SPEED / 60,
      // The plugin owns the pause/resume cycle from here on: it stops the drift
      // on pointerDown and, with stopOnInteraction off, brings it back
      // RECENT_RESTART_MS after the strip settles. A drift therefore can never
      // be swapped in under a finger, which is what made the strip jump when the
      // hand-written hold fired mid-gesture.
      startDelay: RECENT_RESTART_MS,
      playOnInit: false,
      stopOnInteraction: false,
      // Its own mouseenter switch cannot tell a mouse from an iOS tap, whose
      // compatibility mouseenter never gets a matching mouseleave; the hover
      // park stays ours (railHover) for that reason.
      stopOnMouseEnter: false,
      // This one is safe to leave to the plugin: Embla only emits slideFocusStart
      // for a Tab visit, and focusout on the strip resumes — exactly what the
      // hand-written keyboard guard used to mimic.
      stopOnFocusIn: true
    });
    // Embla walks the root's first element child, which is the strip: the
    // wrapper is the root so the clip and the mask share the element the
    // container is translated inside of.
    railEmbla = window.EmblaCarousel(
      railFade,
      { loop: true, align: "start", dragFree: true, duration: RAIL_STEP_DURATION },
      [railAuto]
    );
    // A jump, not a scroll: the strip was rebuilt, not moved by the reader.
    if (returnTo > 0) railEmbla.scrollTo(returnTo, true);
    // A hand on the strip parks the drift for as long as it is there, and the
    // resume is arranged once it is lifted. The plugin stops itself on
    // pointerDown; the flag is what keeps a park flip from re-arming it mid-drag.
    railEmbla.on("pointerDown", () => {
      railDown = true;
      cancelRailRestPoll();
      syncRailAuto();
    });
    railEmbla.on("pointerUp", () => {
      railDown = false;
      resumeRailWhenAtRest();
    });
    // A swipe, an arrow step or a wheel gesture parks the drift, and the restart
    // is due once the strip comes to rest — the plugin's own startDelay.
    railEmbla.on("settle", () => {
      releaseWheelRail();
      syncRailAuto();
    });
    // The plugin also plays on its own after a settle or a focusout, and neither
    // path can see the park rules above. Its play event fires before it marks
    // itself playing, so the stop cannot land inside the handler: it waits a
    // tick, by which time stop() has a playing plugin to stop.
    railEmbla.on("autoScroll:play", () => {
      if (!railParked()) return;
      window.setTimeout(() => {
        if (railAuto && railParked()) railAuto.stop();
      }, 0);
    });
    updateRailButtons();
    syncRailAuto();
  }

  function destroyRail() {
    if (railAuto) railAuto.stop();
    if (railEmbla) railEmbla.destroy();
    railAuto = null;
    railEmbla = null;
    railDown = false;
    cancelRailRestPoll();
    railWheel.base = null;
    railWheel.pending = 0;
    railWheel.settled = true;
    railFade.classList.remove("native");
  }

  // Everything that parks the drift. Hover, focus and the finger on the strip are
  // the plugin's or its own events; these are the states it cannot see.
  function railParked() {
    return (
      !railEmbla ||
      !railAuto ||
      !railInView ||
      railHover ||
      railDown ||
      !railWheel.settled ||
      state.modalId ||
      document.hidden ||
      reduceMotion()
    );
  }

  // Playing is the plugin's whole state machine: stop() while parked, play()
  // otherwise. play() keeps the startDelay from the options, so an un-park and
  // an interaction end up waiting the same beat.
  function syncRailAuto() {
    if (!railAuto) return;
    if (railParked()) {
      railAuto.stop();
      return;
    }
    if (railAuto.isPlaying()) return;
    railAuto.play();
  }

  // The plugin brings the drift back by itself once the strip settles, but a tap
  // that never moves the strip settles nothing — and the stop it does on every
  // pointerDown can cancel a start that was still waiting. So the hand-back is
  // watched here as well: the drift returns once the progress has held still for
  // two frames. scrollProgress() is public API, and handing the strip to the
  // drift mid-momentum is what used to throw it around under the finger.
  let railRestPoll = 0;

  function cancelRailRestPoll() {
    window.cancelAnimationFrame(railRestPoll);
    railRestPoll = 0;
  }

  function resumeRailWhenAtRest() {
    cancelRailRestPoll();
    if (!railEmbla || !railAuto) return;
    let last = railEmbla.scrollProgress();
    let steady = 0;
    let frames = 0;
    const tick = () => {
      railRestPoll = 0;
      if (!railEmbla || !railAuto || railAuto.isPlaying()) return;
      const at = railEmbla.scrollProgress();
      steady = Math.abs(at - last) <= 1e-5 ? steady + 1 : 0;
      last = at;
      frames += 1;
      // The frame cap only guards against a strip that never comes to rest.
      if (steady >= 2 || frames > 240) {
        syncRailAuto();
        return;
      }
      railRestPoll = window.requestAnimationFrame(tick);
    };
    railRestPoll = window.requestAnimationFrame(tick);
  }

  // A looping rail never reaches an end, so both buttons stay live; only the
  // fallback scroller can run out of cards on one side.
  function updateRailButtons() {
    const prev = $("#rail-prev");
    const next = $("#rail-next");
    if (railEmbla) {
      const looping = railEmbla.scrollSnapList().length > 1;
      prev.disabled = !looping;
      next.disabled = !looping;
      railFade.classList.remove("at-start", "at-end");
      railFade.classList.add("loop");
      return;
    }
    const max = updatesTrack.scrollWidth - updatesTrack.clientWidth;
    prev.disabled = updatesTrack.scrollLeft <= 4;
    next.disabled = max <= 4 || updatesTrack.scrollLeft >= max - 4;
    railFade.classList.remove("loop");
    railFade.classList.toggle("at-start", prev.disabled);
    railFade.classList.toggle("at-end", next.disabled);
  }

  function scrollRail(direction) {
    if (railEmbla) {
      // A drift in progress has replaced Embla's own scroll body with the
      // plugin's, which cannot carry a scrollTo: stop it so the step has a
      // body to run on. settle() then brings the drift back after the step. A
      // wheel gesture that has not settled owns the body the same way, and its
      // seek() would eat the step, so it is handed back first.
      releaseWheelRail();
      if (railAuto) railAuto.stop();
      if (direction > 0) railEmbla.scrollNext();
      else railEmbla.scrollPrev();
      return;
    }
    const step = Math.max(updatesTrack.clientWidth * 0.8, 160) * direction;
    updatesTrack.scrollBy({ left: step, behavior: reduceMotion() ? "auto" : "smooth" });
  }

  // Embla has no wheel input of its own, and its public API only moves between
  // snap points. The bridge swaps the engine's scroll body for one that spends
  // the wheel's pixels — the same move embla-carousel-auto-scroll makes — so a
  // trackpad or a tilt wheel drags the strip the way it used to.
  const railWheel = { pending: 0, step: 0, settled: true, base: null };

  function wheelBody(engine) {
    const { location, previousLocation, target, index, indexPrevious, scrollTarget, limit } = engine;
    const body = {
      direction: () => Math.sign(railWheel.step),
      duration: () => -1,
      velocity: () => railWheel.step,
      settled: () => railWheel.settled,
      seek: () => {
        previousLocation.set(location.get());
        railWheel.step = railWheel.pending;
        railWheel.pending = 0;
        location.add(railWheel.step);
        target.set(location.get());
        // Embla's render wraps the loop on its own, but it asks the body which
        // way it just travelled and a spent body answers zero — and its first
        // animation frame seeks twice, so that is the frame every wheel tick
        // lands in. Wrap here instead, with the direction still known.
        const step = Math.sign(railWheel.step);
        for (let pass = 0; pass < 4 && step !== 0; pass += 1) {
          const at = location.get();
          if (step > 0 ? at <= limit.max + 0.1 : at >= limit.min + 0.1) break;
          engine.scrollLooper.loop(step);
          engine.slideLooper.loop();
        }
        const snap = scrollTarget.byDistance(0, false).index;
        if (index.get() !== snap) {
          indexPrevious.set(index.get());
          index.set(snap);
          railEmbla.emit("select");
        }
        railWheel.settled = railWheel.pending === 0;
        return body;
      },
      useBaseFriction: () => body,
      useBaseDuration: () => body,
      useFriction: () => body,
      useDuration: () => body
    };
    return body;
  }

  // Hand the engine back once the wheel body has reported itself settled, so
  // Embla's own loop wrap and inertia take over again.
  function releaseWheelRail() {
    if (!railEmbla || !railWheel.base) return;
    const engine = railEmbla.internalEngine();
    if (engine.scrollBody !== railWheel.base) engine.scrollBody = railWheel.base;
    railWheel.base = null;
    railWheel.pending = 0;
    railWheel.settled = true;
  }

  function wheelRail(deltaX) {
    if (!railEmbla || !railAuto) return;
    if (railWheel.settled) {
      // A new gesture: take the strip over from the drift, which only comes
      // back once the wheel has settled (see settle in layoutRail).
      railAuto.stop();
      const engine = railEmbla.internalEngine();
      railWheel.base = engine.scrollBody;
      engine.scrollBody = wheelBody(engine);
      engine.animation.start();
    }
    railWheel.settled = false;
    // Wheel and scroll positions run opposite ways: a positive deltaX scrolls
    // forward, which is a negative location.
    railWheel.pending -= deltaX;
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
        "data-subscribe": app.bundleID,
        "data-umami-event": "Add single source",
        "data-umami-event-app": app.name,
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
    const subtitle = appSubtitle(app);

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
      subtitle ? h("span", { class: "card-sub", text: subtitle }) : null
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

  // The subscription URLs carry the connection mode. Switching it rewrites the
  // ones already on screen instead of rebuilding the grid, which would throw
  // away the reader's place in it (and restart the rail's drift).
  function refreshSubscriptions() {
    for (const link of document.querySelectorAll("[data-subscribe]")) {
      const app = appById.get(link.dataset.subscribe);
      if (app) link.href = addSourceLink(subscribeURL(app));
    }
  }

  function modalActions(app) {
    const actions = h("div", { class: "m-actions" });
    actions.append(
      h(
        "a",
        {
          class: "btn btn-primary",
          href: addSourceLink(subscribeURL(app)),
          target: "_blank",
          rel: "noopener",
          "data-subscribe": app.bundleID,
          "data-umami-event": "Add single source",
          "data-umami-event-app": app.name
        },
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

    const subtitle = appSubtitle(app);
    const description = appDescription(app);
    const head = h(
      "div",
      { class: "m-head", style: tintStyle(app.tint) },
      iconTile(app, "m-icon"),
      h(
        "div",
        { class: "m-titles" },
        h("p", { class: "m-dev", text: app.developer || "AltStore" }),
        h("h2", { class: "m-title", id: "modal-title", text: app.name }),
        subtitle ? h("p", { class: "m-sub", text: subtitle }) : null,
        pills.length ? h("div", { class: "m-pills" }, ...pills) : null
      )
    );

    const sections = [];
    const shots = screenshotsBlock(app);
    if (shots) sections.push(shots);
    sections.push(
      h("section", { class: "m-section" }, h("h3", { text: t("card.about") }), markdown(description))
    );
    if (app.notes && app.notes !== description && app.notes !== app.description && app.notes !== app.subtitle) {
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

  // The sheet owns a history entry, so the back button — and the edge swipe on
  // iOS, which is the reflex way to dismiss a sheet there — closes it instead of
  // leaving the page. The hash doubles as a deep link: #app=<bundle id>.
  const SHEET_HASH = "#app=";

  function sheetIdFromHash() {
    const hash = window.location.hash;
    if (!hash.startsWith(SHEET_HASH)) return "";
    try {
      return decodeURIComponent(hash.slice(SHEET_HASH.length));
    } catch (error) {
      return "";
    }
  }

  function clearSheetHash() {
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }

  // aria-modal is not honoured by every screen reader, so what the sheet covers
  // is taken out of the tab order and the accessibility tree by hand.
  function setBackgroundInert(inert) {
    for (const element of [document.querySelector(".nav"), document.querySelector("main")]) {
      if (!element) continue;
      if (inert) element.setAttribute("inert", "");
      else element.removeAttribute("inert");
    }
  }

  // The page behind the sheet must not scroll — but it must not move either.
  // Pinning the body with `position: fixed` is the old iOS trick, and it is what
  // made the catalog flash: the scroll offset is destroyed on open and restored
  // on close, so the frame that un-pins asks the compositor for a brand new tile
  // set of the whole viewport, and the sheet's backdrop-filter has to be
  // re-sampled from that. `overflow: hidden` alone holds wheel and keyboard
  // scrolling everywhere, and iOS, which scrolls the document under a finger
  // regardless, is held by the touchmove guard on the sheet itself.
  function lockPage() {
    state.locked = true;
    document.documentElement.classList.add("is-locked");
  }

  function unlockPage() {
    state.locked = false;
    document.documentElement.classList.remove("is-locked");
  }

  function openModal(id, opener, fromHistory) {
    const app = appById.get(id);
    if (!app) return;
    window.clearTimeout(closeTimer);
    state.modalId = id;
    state.lastFocus = opener || document.activeElement;
    // One entry per opening; closing pops it again (see closeModal).
    if (!fromHistory) {
      window.history.pushState({ sheet: id }, "", SHEET_HASH + encodeURIComponent(id));
      state.sheetPushed = true;
    }
    // The sheet covers the rail: park the drift while it is open.
    syncRailAuto();
    renderModalBody();
    modal.hidden = false;
    modalBody.scrollTop = 0;
    setBackgroundInert(true);
    if (!state.locked) lockPage();
    // Force a layout pass so the sheet transitions in from its closed state.
    void modalPanel.offsetHeight;
    requestAnimationFrame(() => {
      modal.classList.add("open");
      modalPanel.focus({ preventScroll: true });
    });
  }

  function closeModal(fromHistory) {
    if (!state.modalId) return;
    state.modalId = null;
    modal.classList.remove("open");
    // Closing by hand pops the entry the sheet pushed; the popstate handler
    // then finds nothing left to close. A sheet opened from an #app= link has
    // no entry of its own, so its hash is cleared instead.
    const pushed = state.sheetPushed;
    state.sheetPushed = false;
    if (!fromHistory) {
      if (pushed) window.history.back();
      else if (sheetIdFromHash()) clearSheetHash();
    }
    const finish = () => {
      closeTimer = 0;
      modal.hidden = true;
      modalBody.replaceChildren();
      setBackgroundInert(false);
      unlockPage();
      const opener = state.lastFocus;
      state.lastFocus = null;
      if (opener && opener.isConnected && typeof opener.focus === "function") {
        opener.focus({ preventScroll: true });
      }
      // Back where it was: the rail picks up again once the sheet is gone.
      syncRailAuto();
    };
    // The longest of the sheet's own transitions (panel 0.5s) has to be over
    // before the node leaves the tree: removing a live `backdrop-filter` layer
    // mid-fade forces the page behind it to be re-sampled from scratch.
    if (reduceMotion()) finish();    else closeTimer = window.setTimeout(finish, 520);
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
    // Repository path -> staged file. Without it every image keeps its path.
    const mediaFiles = config.mediaFiles && typeof config.mediaFiles === "object"
      ? config.mediaFiles
      : {};
    const proxyPrefixValue = config.proxyPrefix || DEFAULT_PROXY_PREFIX;
    const repoParts = rawBase ? rawBase.split("/") : [];
    const repo =
      config.repo ||
      (repoParts.length > 4 ? "https://github.com/" + repoParts[3] + "/" + repoParts[4] : "");
    const allSource = config.allSource || (rawBase ? rawBase + "all-apps.json" : "");
    const allSourceProxy =
      config.allSourceProxy || (rawBase ? rawBase + "all-apps-proxy.json" : "");
    // Language -> { bundle identifier -> { subtitle, description } }. The
    // catalog itself carries one language per app, so the page's other
    // languages come from site/i18n/, folded into config.json by the build.
    const overlay = config.i18n && typeof config.i18n === "object" ? config.i18n : {};

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
      const bundleID = app.bundleIdentifier || app.name || "";
      const i18n = {};
      for (const [lang, table] of Object.entries(overlay)) {
        const entry = table && table[bundleID];
        if (entry && typeof entry === "object") i18n[lang] = entry;
      }
      apps.push({
        bundleID,
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
        sourceProxy: folder ? rawBase + "apps/" + folder + "/apps-proxy.json" : "",
        i18n
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
      mediaFiles,
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

  // A connection switch changes hrefs and nothing else: the rail's promo tiles
  // carry no proxy URLs, so it is left alone, and the grid keeps its cards.
  function renderMode() {
    applyLabels();
    if (!data) return;
    applyData();
    refreshSubscriptions();
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

  // The browser resolves a #hash before the catalog exists, so a section it
  // jumped to has been reshaped by the cards that land after it. The sheet
  // links are left alone: openModal() owns those.
  function realignToHash() {
    const hash = window.location.hash;
    if (!hash || hash.startsWith(SHEET_HASH)) return;
    let target = null;
    try {
      target = document.querySelector(hash);
    } catch (error) {
      return; // not a selector: there is nothing to align to
    }
    if (!target) return;
    window.scrollTo({
      top: target.getBoundingClientRect().top + (window.scrollY || 0),
      behavior: "instant"
    });
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
      realignToHash();
      // A deep link (#app=<bundle id>) opens straight onto that app.
      const deepLink = sheetIdFromHash();
      if (deepLink && appById.has(deepLink)) openModal(deepLink, null, true);
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
      renderMode();
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

  // Only a real pointer can hover, and WebKit drops the pointerleave that ends
  // a scroll gesture, so the release is caught wherever it happens: a hover
  // flag left behind would park the rail for good.
  const clearRailHover = () => {
    if (!railHover) return;
    railHover = false;
    syncRailAuto();
  };
  railFade.addEventListener("pointerenter", (event) => {
    if (event.pointerType === "touch") return;
    railHover = true;
    syncRailAuto();
  });
  railFade.addEventListener("pointerleave", clearRailHover);
  railFade.addEventListener("pointercancel", clearRailHover);
  // A touch that ends outside the rail is the same release, and Embla's own
  // pointerUp can be missed on a cancelled gesture: whichever comes last wins.
  const releaseRailTouch = () => {
    clearRailHover();
    if (!railDown) return;
    railDown = false;
    resumeRailWhenAtRest();
  };
  window.addEventListener("pointerup", (event) => {
    if (event.pointerType === "touch") releaseRailTouch();
  }, true);
  window.addEventListener("pointercancel", (event) => {
    if (event.pointerType === "touch") releaseRailTouch();
  }, true);
  // A sideways wheel or trackpad swipe drags the strip; anything with more
  // vertical than horizontal travel is the page's to scroll, so only the
  // former is taken over. The fallback scroller needs no bridge — it scrolls
  // natively.
  railFade.addEventListener(
    "wheel",
    (event) => {
      if (!railEmbla) return;
      const vertical = Math.abs(event.deltaY);
      if (!event.deltaX || Math.abs(event.deltaX) <= vertical) return;
      let delta = event.deltaX;
      if (event.deltaMode === 1) delta *= 16; // lines
      else if (event.deltaMode === 2) delta *= railFade.clientWidth; // pages
      event.preventDefault();
      wheelRail(delta);
    },
    { passive: false }
  );
  // Tab focus and its release are the auto-scroll plugin's own job (stopOnFocusIn
  // above); it already ignores a card focused by a pointer click.
  document.addEventListener("visibilitychange", () => syncRailAuto());
  $("#rail-prev").addEventListener("click", () => scrollRail(-1));
  $("#rail-next").addEventListener("click", () => scrollRail(1));

  // The fallback scroller is the only strip whose arrows follow a position.
  updatesTrack.addEventListener(
    "scroll",
    () => {
      if (!railEmbla) updateRailButtons();
    },
    { passive: true }
  );

  // Card width follows the viewport, so the fitted promo names need a pass after
  // a resize. Embla re-measures on its own (its ResizeObserver watches the strip
  // and the cards), and calling reInit() here would be a hard reset: on iOS the
  // toolbar collapsing during a page scroll fires resize, and a reInit snaps the
  // drifting strip back to the nearest card.
  window.addEventListener("resize", () => {
    window.clearTimeout(railResizeTimer);
    railResizeTimer = window.setTimeout(() => {
      fitPromoNames([...updatesTrack.children]);
      updateRailButtons();
      syncRailAuto();
    }, 180);
  });

  // Re-park when the reduced-motion preference flips while the page is open.
  const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  if (motionQuery.addEventListener) {
    motionQuery.addEventListener("change", () => syncRailAuto());
  }

  // Only drift while the section is on screen.
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(
      (entries) => {
        railInView = entries[0].isIntersecting;
        syncRailAuto();
      },
      { threshold: 0.15 }
    ).observe($("#updates"));
  }

  $("#modal-close").addEventListener("click", () => closeModal());
  modal.addEventListener("click", (event) => {
    if (!event.target.classList.contains("modal-backdrop")) return;
    closeModal();
  });
  // iOS scrolls the document under a finger even with `overflow: hidden` on the
  // root, which is why the body used to be pinned — and un-pinning it is what
  // re-rastered the catalog on close. The gesture is refused here instead, in the
  // one place it can only be the page's: everything in the sheet that is not the
  // scrolling body. That body's `overscroll-behavior: contain` already stops it
  // from chaining out at its ends.
  modal.addEventListener(
    "touchmove",
    (event) => {
      if (event.target.closest(".modal-scroll")) return;
      if (event.cancelable) event.preventDefault();
    },
    { passive: false }
  );
  document.addEventListener("keydown", (event) => {
    if (!state.modalId) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeModal();
    } else if (event.key === "Tab") {
      trapFocus(event);
    }
  });
  // A history step either leaves the sheet or lands on one: the hash says which
  // app the entry belongs to. Closing by hand pops back here with no sheet id,
  // and finds nothing left to do.
  window.addEventListener("popstate", () => {
    const id = sheetIdFromHash();
    if (state.modalId) {
      if (id !== state.modalId) closeModal(true);
      return;
    }
    if (id && appById.has(id)) openModal(id, null, true);
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
