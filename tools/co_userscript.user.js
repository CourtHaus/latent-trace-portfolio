// ==UserScript==
// @name         CO Cold Case Index Scraper
// @namespace    casesignal
// @version      1.0
// @description  Scrape all paginated case IDs from Colorado CBI cold case search
// @match        https://apps.colorado.gov/apps/coldcase/search.html*
// @grant        none
// @run-at       document-end
// ==/UserScript==

(function () {
  "use strict";

  var STATE_KEY = "coScrapeState";

  function getState() {
    try {
      var s = JSON.parse(localStorage.getItem(STATE_KEY) || "null");
      return s || { mode: "idle", page: 0, totalPages: 0, data: [] };
    } catch (e) {
      return { mode: "idle", page: 0, totalPages: 0, data: [] };
    }
  }
  function setState(s) { localStorage.setItem(STATE_KEY, JSON.stringify(s)); }

  function injectUI() {
    if (document.getElementById("co-scrape-panel")) return;
    var panel = document.createElement("div");
    panel.id = "co-scrape-panel";
    panel.style.cssText =
      "position:fixed;top:10px;right:10px;z-index:99999;" +
      "background:#fff;border:2px solid #333;padding:12px;" +
      "font-family:monospace;font-size:13px;" +
      "box-shadow:0 2px 8px rgba(0,0,0,0.2);max-width:320px;";
    panel.innerHTML =
      '<div style="font-weight:bold;margin-bottom:8px;">CO Scrape</div>' +
      '<div id="co-scrape-status">idle</div>' +
      '<div style="margin-top:8px;">' +
      '<button id="co-scrape-start" style="padding:4px 8px;margin-right:4px;">Start</button>' +
      '<button id="co-scrape-stop" style="padding:4px 8px;margin-right:4px;">Stop</button>' +
      '<button id="co-scrape-reset" style="padding:4px 8px;margin-right:4px;">Reset</button>' +
      '<button id="co-scrape-export" style="padding:4px 8px;">Export</button>' +
      "</div>";
    document.body.appendChild(panel);
    document.getElementById("co-scrape-start").onclick = startScrape;
    document.getElementById("co-scrape-stop").onclick = stopScrape;
    document.getElementById("co-scrape-reset").onclick = resetScrape;
    document.getElementById("co-scrape-export").onclick = exportData;
    updateStatusUI();
  }

  function updateStatusUI() {
    var s = getState();
    var el = document.getElementById("co-scrape-status");
    if (!el) return;
    if (s.mode === "idle") {
      el.textContent = "idle (" + s.data.length + " cached)";
    } else if (s.mode === "active") {
      el.textContent = "page " + s.page + " / " + (s.totalPages || "?") +
                       " (" + s.data.length + " so far)";
    } else if (s.mode === "done") {
      el.textContent = "DONE: " + s.data.length + " cases - click Export";
    }
  }

  function scrapeCurrentPage() {
    var seen = {};
    var state = getState();
    for (var i = 0; i < state.data.length; i++) seen[state.data[i].id] = true;
    // CBI renders TWO formats:
    //   1. Grid/carousel (page 1 only): <a aria-label="Cold case file for X" href="casedetail.html?id=N">
    //   2. Table (pages 2+): <a href="casedetail.html?id=N">X</a> + adjacent <img alt="Case photo M for X (GENDER)">
    // Match ALL anchors with casedetail.html?id= href; extract name from any available source.
    var links = document.querySelectorAll('a[href*="casedetail.html?id="]');
    var newCases = [];
    var byId = {};  // dedupe per-page (table may have duplicate anchors per row)
    for (var i = 0; i < links.length; i++) {
      var a = links[i];
      var href = a.getAttribute("href") || "";
      var idMatch = href.match(/id=(\d+)/);
      if (!idMatch) continue;
      var id = parseInt(idMatch[1], 10);
      if (seen[id] || byId[id]) continue;

      var name = null;
      // Source 1: aria-label="Cold case file for X"
      var labelAttr = a.getAttribute("aria-label") || "";
      var labelMatch = labelAttr.match(/Cold case file for\s+(.+)/i);
      if (labelMatch) {
        name = labelMatch[1].trim();
      }
      // Source 2: anchor text content (table-row name link)
      if (!name) {
        var text = (a.textContent || "").trim();
        // Skip if text is "‹‹", "›", "1", "2", etc. (pagination controls)
        if (text && text.length > 1 && !/^[‹›0-9.\s«»<>]+$/.test(text)) {
          name = text;
        }
      }
      // Source 3: adjacent <img alt="Case photo N for X (GENDER)">
      if (!name) {
        var img = a.querySelector("img") || (a.parentElement && a.parentElement.querySelector("img"));
        if (img) {
          var alt = img.getAttribute("alt") || "";
          var altMatch = alt.match(/Case photo \d+ for\s+(.+?)(?:\s*\([^)]+\))?$/i);
          if (altMatch) name = altMatch[1].trim();
        }
      }
      // Source 4: nearby row/parent's img alt (table layout)
      if (!name) {
        var row = a.closest("tr, .caseHolderPerson, li");
        if (row) {
          var rowImg = row.querySelector("img[alt]");
          if (rowImg) {
            var rowAlt = rowImg.getAttribute("alt") || "";
            var rowMatch = rowAlt.match(/Case photo \d+ for\s+(.+?)(?:\s*\([^)]+\))?$/i);
            if (rowMatch) name = rowMatch[1].trim();
          }
        }
      }

      if (!name) continue;  // anchor with no extractable name (e.g., pagination control)

      byId[id] = true;
      newCases.push({
        id: id,
        name: name.replace(/\s+/g, " "),
      });
    }
    return newCases;
  }

  function getTotalPages() {
    var html = document.documentElement.innerHTML;
    var m = html.match(/of\s+(\d+)\s+total/);
    if (!m) return 0;
    var total = parseInt(m[1], 10);
    // Page size is 5 on table-format pages (verified live).
    // We over-estimate by ceiling — extras are no-ops (newCases=0).
    return Math.ceil(total / 5);
  }

  function startScrape() {
    var totalPages = getTotalPages();
    if (totalPages === 0) {
      alert("No search results detected on this page. First: select HOMICIDE + OPEN and click Submit Search. Then click Start.");
      return;
    }
    var state = { mode: "active", page: 1, totalPages: totalPages, data: [] };
    setState(state);
    advance();
  }

  function stopScrape() {
    var s = getState();
    s.mode = "idle";
    setState(s);
    updateStatusUI();
  }

  function resetScrape() {
    if (!confirm("Reset all collected data?")) return;
    localStorage.removeItem(STATE_KEY);
    updateStatusUI();
  }

  function exportData() {
    var s = getState();
    if (s.data.length === 0) {
      alert("No data collected yet.");
      return;
    }
    var json = JSON.stringify(s.data, null, 2);
    var blob = new Blob([json], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "co_case_index.json";
    a.click();
    URL.revokeObjectURL(url);
  }

  function advance() {
    var s = getState();
    if (s.mode !== "active") return;

    var newCases = scrapeCurrentPage();
    for (var i = 0; i < newCases.length; i++) s.data.push(newCases[i]);
    setState(s);
    updateStatusUI();

    if (s.page >= s.totalPages) {
      s.mode = "done";
      setState(s);
      updateStatusUI();
      setTimeout(exportData, 500);
      return;
    }

    var nextPage = s.page + 1;
    s.page = nextPage;
    setState(s);

    setTimeout(function () {
      var pageInput = document.getElementById("currentPage");
      var resetInput = document.getElementById("resetSearch");
      if (pageInput) pageInput.value = nextPage;
      if (resetInput) resetInput.value = "false";
      var form = document.getElementById("casefilter");
      if (form) form.submit();
    }, 800);
  }

  function init() {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
      return;
    }
    injectUI();
    var s = getState();
    if (s.mode === "active") {
      setTimeout(advance, 1000);
    }
  }

  init();
})();
