(() => {
  "use strict";

  const RAW_HOST = "https://raw.githubusercontent.com/";
  const RELEASE_DOWNLOAD = /^https:\/\/github\.com\/[^/]+\/[^/]+\/releases\/(?:latest\/)?download\//;
  const DEFAULT_PROXY_PREFIX = "https://gh-proxy.com/";
  const STORE_KEY = { lang: "altgallery.lang", mode: "altgallery.mode" };
  const SVG_NS = "http://www.w3.org/2000/svg";

  // Filled by boot() from all-apps.json; null while the page is loading.
  let data = null;
  let appById = new Map();

  // preview.html inlines the catalog; the deployed page fetches it instead.
  const EMBEDDED = window.__ALTGALLERY_DATA__ || null;

  const state = { lang: "en", mirror: false, query: "", sort: "updated", open: null, focus: null };

  const STRINGS = {
    en: {
      "lang.label": "Language",
      "mode.label": "Connection",
      "mode.direct": "Direct",
      "mode.mirror": "Mirror",
      "hero.sub": "Curated AltStore sources for IPA projects on GitHub.",
      "hero.clients": "Works with AltStore, SideStore, LiveContainer and other compatible clients.",
      "hero.addAll": "Add all sources",
      "hero.repo": "View on GitHub",
      "hero.modeDirect": "Links and images use github.com directly.",
      "hero.modeMirror": "Links and images go through gh-proxy.com.",
      "stats.apps": "{n} apps",
      "stats.updated": "Updated {d}",
      "updates.title": "Recent updates",
      "search.placeholder": "Search apps, developers or keywords",
      "search.label": "Search apps",
      "apps.sortLabel": "Sort",
      "sort.updated": "Recently updated",
      "sort.name": "Name A–Z",
      "apps.count": "{n} apps",
      "apps.empty": "No apps match your search.",
      "load.loading": "Loading the catalog…",
      "load.error": "Could not load the catalog. Check your connection and reload, or open",
      "card.add": "Add source",
      "card.details": "Details",
      "card.hide": "Hide",
      "card.version": "v{v}",
      "card.minOS": "iOS {v}+",
      "card.updated": "Updated {d}",
      "card.about": "About",
      "card.screenshots": "Screenshots",
      "card.screenshotAlt": "Screenshot {n}",
      "card.notes": "Release notes",
      "card.github": "GitHub",
      "card.download": "Download IPA",
      "footer.note": "Catalog generated from GitHub Releases with AltGen; sources refresh every 6 hours.",
      "footer.request": "Request an app"
    },
    zh: {
      "lang.label": "语言",
      "mode.label": "连接方式",
      "mode.direct": "直连",
      "mode.mirror": "镜像",
      "hero.sub": "精选 GitHub 上的 IPA 开源项目 AltStore 软件源。",
      "hero.clients": "兼容 AltStore、SideStore、LiveContainer 等客户端。",
      "hero.addAll": "添加全部源",
      "hero.repo": "在 GitHub 查看",
      "hero.modeDirect": "链接和图片直连 GitHub。",
      "hero.modeMirror": "链接和图片经由 gh-proxy.com 镜像。",
      "stats.apps": "{n} 个 App",
      "stats.updated": "更新于 {d}",
      "updates.title": "最近更新",
      "search.placeholder": "搜索 App、开发者或关键词",
      "search.label": "搜索 App",
      "apps.sortLabel": "排序",
      "sort.updated": "最近更新",
      "sort.name": "名称 A–Z",
      "apps.count": "{n} 个 App",
      "apps.empty": "没有匹配的 App。",
      "load.loading": "正在加载目录…",
      "load.error": "无法加载目录，请检查网络后刷新，或直接打开",
      "card.add": "添加源",
      "card.details": "详情",
      "card.hide": "收起",
      "card.version": "v{v}",
      "card.minOS": "iOS {v}+",
      "card.updated": "更新于 {d}",
      "card.about": "简介",
      "card.screenshots": "截图",
      "card.screenshotAlt": "截图 {n}",
      "card.notes": "发布说明",
      "card.github": "GitHub",
      "card.download": "下载 IPA",
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
  const CHEV_ICON = ["M4.4 6.2 8 9.8l3.6-3.6"];

  function proxyPrefix() {
    return (data && data.proxyPrefix) || DEFAULT_PROXY_PREFIX;
  }

  function proxyURL(url) {
    if (!state.mirror || !url) return url;
    if (url.startsWith(RAW_HOST) || RELEASE_DOWNLOAD.test(url)) return proxyPrefix() + url;
    return url;
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

  function ensureFavicon() {
    let link = document.querySelector('link[rel="icon"]');
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      document.head.append(link);
    }
    link.href = proxyURL(data.icon);
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
    $("#sort").value = state.sort;
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
    $("#brand-mark").src = proxyURL(data.icon);
    $("#hero-icon").src = proxyURL(data.icon);
    $("#add-all").href = addSourceLink(state.mirror ? proxyPrefix() + data.allSourceProxy : data.allSource);
    $("#add-all").removeAttribute("aria-disabled");
    $("#add-all-icon").replaceChildren(svgIcon(PLUS_ICON, 14));
    $("#footer-source").href = data.allSource;
    $("#footer-source").textContent = "all-apps.json";
    $("#footer-proxy").href = proxyPrefix() + data.allSourceProxy;
    $("#footer-proxy").textContent = "all-apps-proxy.json";

    $("#search").disabled = false;
    $("#sort").disabled = false;
    grid.setAttribute("aria-busy", "false");

    ensureFavicon();
  }

  function updateCard(item) {
    const card = h("a", {
      class: "update",
      href: item.url,
      target: "_blank",
      rel: "noopener",
      style: safeTint(item.tint) ? "--tint:" + safeTint(item.tint) : null
    });
    const media = h("div", { class: "update-media" });
    if (item.image) {
      const image = h("img", { src: proxyURL(item.image), alt: "", loading: "lazy", decoding: "async" });
      image.addEventListener("error", () => media.classList.add("noimg"));
      media.append(image);
    } else {
      media.classList.add("noimg");
    }
    const app = appById.get(item.appID);
    card.append(
      media,
      h(
        "div",
        { class: "update-body" },
        h(
          "div",
          { class: "update-top" },
          h("span", { class: "update-app", text: app ? app.name : item.app }),
          h("span", { text: fmtDate(item.date) })
        ),
        h("p", { class: "update-caption", text: item.caption || item.title })
      )
    );
    return card;
  }

  function renderUpdates() {
    if (!data) return;
    const track = $("#updates-track");
    const items = data.news.slice(0, 12);
    track.replaceChildren(...items.map(updateCard));
    $("#updates").hidden = items.length === 0;
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
        appendInline(row, cells.join("  \u00b7  "));
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
    const list = (app.screenshots || []).slice(0, 14);
    if (!list.length) return null;
    const strip = h("div", { class: "shots" });
    list.forEach((url, index) => {
      const image = h("img", {
        src: proxyURL(url),
        alt: t("card.screenshotAlt", { n: index + 1 }),
        loading: "lazy",
        decoding: "async"
      });
      image.addEventListener("error", () => image.remove());
      strip.append(image);
    });
    return h("div", null, h("h4", { text: t("card.screenshots") }), strip);
  }

  function detailLinks(app) {
    const links = h("div", { class: "detail-links" });
    if (app.repo) {
      links.append(h("a", { class: "link-btn", href: app.repo, target: "_blank", rel: "noopener", text: t("card.github") }));
    }
    if (app.download) {
      links.append(h("a", { class: "link-btn", href: proxyURL(app.download), target: "_blank", rel: "noopener", text: t("card.download") }));
    }
    return links;
  }

  function detailsBlock(app) {
    const shots = screenshotsBlock(app);
    const about = h("div", null, h("h4", { text: t("card.about") }), markdown(app.description || app.subtitle));
    const textColumn = [about];
    if (app.notes && app.notes !== app.description) {
      textColumn.push(
        h("div", { class: "notes" }, h("h4", { text: t("card.notes") + (app.version ? " · v" + app.version : "") }), markdown(app.notes))
      );
    }
    const columns = h("div", { class: "details-cols" + (shots ? "" : " one") });
    if (shots) columns.append(shots);
    columns.append(h("div", null, ...textColumn, detailLinks(app)));
    return h("div", { class: "details" }, columns);
  }

  function appCard(app) {
    const isOpen = state.open === app.bundleID;
    const tint = safeTint(app.tint);
    const tile = h("div", { class: "icon-tile", style: tint ? "--tint:" + tint : null });
    tile.append(h("span", { class: "icon-letter", "aria-hidden": "true", text: (app.name || "?").slice(0, 1).toUpperCase() }));
    if (app.icon) {
      const icon = h("img", { src: proxyURL(app.icon), alt: "", width: 52, height: 52, loading: "lazy", decoding: "async" });
      icon.addEventListener("error", () => icon.remove());
      tile.append(icon);
    }

    const addButton = h(
      "a",
      {
        class: "btn btn-add",
        href: addSourceLink(subscribeURL(app)),
        target: "_blank",
        rel: "noopener"
      },
      svgIcon(PLUS_ICON, 13),
      t("card.add")
    );

    const detailsId = "details-" + app.bundleID.replace(/[^a-zA-Z0-9_-]/g, "-");
    const detailsButton = h(
      "button",
      {
        type: "button",
        class: "btn btn-details",
        "aria-expanded": String(isOpen),
        "aria-controls": detailsId,
        onclick: () => toggleDetails(app)
      },
      t(isOpen ? "card.hide" : "card.details"),
      (() => {
        const chevron = svgIcon(CHEV_ICON, 13);
        chevron.classList.add("chev");
        return chevron;
      })()
    );

    const metaNodes = [];
    if (app.minOS) metaNodes.push(h("span", { text: t("card.minOS", { v: app.minOS }) }));
    const size = fmtSize(app.size);
    if (size) metaNodes.push(h("span", { text: size }));
    if (app.date) metaNodes.push(h("span", { text: t("card.updated", { d: fmtDate(app.date) }) }));

    const card = h(
      "article",
      {
        class: "card" + (isOpen ? " open" : ""),
        "data-id": app.bundleID,
        style: tint ? "--tint:" + tint : null
      },
      h(
        "div",
        { class: "card-head" },
        tile,
        h(
          "div",
          { class: "app-titles" },
          h("h3", { class: "app-name", text: app.name }),
          h("p", { class: "app-dev", text: app.developer || " " })
        ),
        h("span", { class: "ver", text: t("card.version", { v: app.version }) })
      ),
      h("p", { class: "app-sub", text: app.subtitle }),
      metaNodes.length ? h("div", { class: "meta" }, ...metaNodes) : null,
      h("div", { class: "card-actions" }, addButton, detailsButton),
      isOpen ? h("div", { id: detailsId }, detailsBlock(app)) : null
    );
    return card;
  }

  function toggleDetails(app) {
    state.open = state.open === app.bundleID ? null : app.bundleID;
    state.focus = app.bundleID;
    renderApps();
  }

  function renderApps() {
    if (!data) return;
    const list = visibleApps();
    grid.replaceChildren(...list.map(appCard));
    $("#apps-count").textContent = t("apps.count", { n: list.length });
    $("#empty").hidden = list.length > 0;

    if (state.focus) {
      const bundleID = state.focus;
      state.focus = null;
      const card = grid.querySelector('[data-id="' + (window.CSS && CSS.escape ? CSS.escape(bundleID) : bundleID) + '"]');
      const button = card ? card.querySelector(".btn-details") : null;
      if (button) button.focus({ preventScroll: true });
    }
  }

  function deriveRawBase(iconURL) {
    const match = String(iconURL || "").match(
      /^(https:\/\/raw\.githubusercontent\.com\/[^/]+\/[^/]+\/(?:refs\/heads\/[^/]+\/|master\/))/
    );
    return match ? match[1] : "";
  }

  // Shape all-apps.json into what the page renders, and attach the URLs of the
  // prepared per-app proxy sources so the Mirror switch can subscribe to them.
  function prepare(source, config) {
    const rawBase = config.rawBase || deriveRawBase(source.iconURL);
    const proxyPrefix = config.proxyPrefix || DEFAULT_PROXY_PREFIX;
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
      proxyPrefix,
      repo,
      allSource,
      allSourceProxy,
      updated: dates.length ? dates.reduce((max, value) => (value > max ? value : max), dates[0]) : "",
      apps,
      news
    };
  }

  async function fetchJSON(url) {
    const response = await fetch(url, { cache: "no-cache" });
    if (!response.ok) throw new Error(url + ": HTTP " + response.status);
    return response.json();
  }

  function renderSkeleton() {
    const cards = [];
    for (let index = 0; index < 6; index += 1) {
      cards.push(
        h(
          "div",
          { class: "card skeleton", "aria-hidden": "true" },
          h(
            "div",
            { class: "card-head" },
            h("div", { class: "sk-icon" }),
            h("div", { class: "sk-lines" }, h("div", { class: "sk-line w60" }), h("div", { class: "sk-line w40" }))
          ),
          h("div", { class: "sk-line w90" }),
          h("div", { class: "sk-line w70" })
        )
      );
    }
    grid.replaceChildren(...cards);
  }

  function showError() {
    grid.replaceChildren();
    grid.setAttribute("aria-busy", "false");
    const status = $("#status");
    status.replaceChildren(
      document.createTextNode(t("load.error") + " "),
      h("a", { href: "all-apps.json", target: "_blank", rel: "noopener", text: "all-apps.json" })
    );
    status.hidden = false;
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

  function render() {
    applyLabels();
    if (!data) return;
    applyData();
    renderUpdates();
    renderApps();
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

  $("#search").addEventListener("input", (event) => {
    state.query = event.target.value;
    renderApps();
  });

  $("#sort").addEventListener("change", (event) => {
    state.sort = event.target.value;
    renderApps();
  });

  initState();
  boot();
})();
