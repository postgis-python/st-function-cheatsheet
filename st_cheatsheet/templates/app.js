/* Client-side filtering, ranking and keyboard navigation for the cheatsheet page.
 *
 * The page is fully rendered server-side: every card is already in the DOM, so the
 * content is readable, printable and deep-linkable with JavaScript disabled. This
 * script only hides, reorders and highlights what is already there.
 */
(function () {
  "use strict";

  var DATA = window.__ST_CHEATSHEET__ || { entries: [] };
  var entries = DATA.entries;

  var search = document.getElementById("search");
  var categorySelect = document.getElementById("category");
  var indexOnly = document.getElementById("index-only");
  var status = document.getElementById("status");
  var indexList = document.getElementById("index-list");
  var cards = document.getElementById("cards");
  var empty = document.getElementById("empty");

  var cardFor = {};
  var itemFor = {};
  entries.forEach(function (entry) {
    cardFor[entry.slug] = document.getElementById(entry.slug);
    itemFor[entry.slug] = document.getElementById("nav-" + entry.slug);
  });

  var visible = entries.slice();
  var cursor = -1;

  /* ---- scoring ------------------------------------------------------------ */

  /** Subsequence match: every query character appears in order. Tolerates typos
   *  far less than a full edit distance, but is predictable and fast. */
  function subsequenceScore(query, target) {
    var qi = 0;
    var score = 0;
    var streak = 0;
    for (var ti = 0; ti < target.length && qi < query.length; ti++) {
      if (target[ti] === query[qi]) {
        streak += 1;
        score += streak;
        qi += 1;
      } else {
        streak = 0;
      }
    }
    return qi === query.length ? score : -1;
  }

  function rank(entry, query) {
    var name = entry.name.toLowerCase();
    var bare = name.indexOf("st_") === 0 ? name.slice(3) : name;
    if (name === query || bare === query) return 1000;
    if (name.indexOf(query) === 0 || bare.indexOf(query) === 0) return 700;
    if (name.indexOf(query) !== -1) return 500;
    for (var i = 0; i < entry.tags.length; i++) {
      if (entry.tags[i].indexOf(query) !== -1) return 400;
    }
    if (entry.summary.toLowerCase().indexOf(query) !== -1) return 300;
    var sub = subsequenceScore(query, bare);
    return sub >= 0 ? 100 + sub : -1;
  }

  /* ---- filtering ---------------------------------------------------------- */

  function currentMatches() {
    var query = search.value.trim().toLowerCase();
    var category = categorySelect.value;
    var gistOnly = indexOnly.checked;

    var pool = entries.filter(function (entry) {
      if (category !== "all" && entry.category !== category) return false;
      if (gistOnly && !entry.gist) return false;
      return true;
    });

    if (!query) return pool;

    return pool
      .map(function (entry) {
        return { entry: entry, score: rank(entry, query) };
      })
      .filter(function (hit) {
        return hit.score >= 0;
      })
      .sort(function (a, b) {
        return b.score - a.score || a.entry.name.length - b.entry.name.length;
      })
      .map(function (hit) {
        return hit.entry;
      });
  }

  function apply() {
    visible = currentMatches();
    var shown = {};
    visible.forEach(function (entry, position) {
      shown[entry.slug] = position;
    });

    entries.forEach(function (entry) {
      var hit = Object.prototype.hasOwnProperty.call(shown, entry.slug);
      cardFor[entry.slug].classList.toggle("hidden", !hit);
      var item = itemFor[entry.slug];
      item.classList.toggle("hidden", !hit);
      item.setAttribute("aria-hidden", hit ? "false" : "true");
      if (hit) item.style.order = String(shown[entry.slug]);
    });

    // Group headings only make sense while the list is in its natural order.
    var ordered = !search.value.trim();
    Array.prototype.forEach.call(document.querySelectorAll(".index__group"), function (heading) {
      var group = heading.getAttribute("data-category");
      var anyVisible = visible.some(function (entry) {
        return entry.category === group;
      });
      heading.classList.toggle("hidden", !ordered || !anyVisible);
    });
    indexList.style.display = ordered ? "block" : "flex";
    indexList.style.flexDirection = ordered ? "" : "column";

    empty.classList.toggle("hidden", visible.length > 0);
    cards.classList.toggle("hidden", visible.length === 0);

    status.textContent =
      visible.length === entries.length
        ? entries.length + " functions"
        : visible.length + " of " + entries.length + " functions";

    setCursor(visible.length ? 0 : -1, false);
  }

  /* ---- keyboard navigation ------------------------------------------------ */

  function setCursor(next, scroll) {
    cursor = next;
    entries.forEach(function (entry) {
      var node = itemFor[entry.slug];
      node.removeAttribute("data-active");
      node.setAttribute("aria-selected", "false");
    });
    if (cursor < 0 || cursor >= visible.length) {
      search.removeAttribute("aria-activedescendant");
      return;
    }
    var active = itemFor[visible[cursor].slug];
    active.setAttribute("data-active", "true");
    active.setAttribute("aria-selected", "true");
    search.setAttribute("aria-activedescendant", active.id);
    if (scroll) active.scrollIntoView({ block: "nearest" });
  }

  function move(delta) {
    if (!visible.length) return;
    var next = cursor + delta;
    if (next < 0) next = visible.length - 1;
    if (next >= visible.length) next = 0;
    setCursor(next, true);
  }

  function openCursor() {
    if (cursor < 0 || cursor >= visible.length) return;
    var slug = visible[cursor].slug;
    window.location.hash = slug;
    cardFor[slug].scrollIntoView({ block: "start", behavior: "smooth" });
    cardFor[slug].focus({ preventScroll: true });
  }

  document.addEventListener("keydown", function (event) {
    if (event.key === "/" && document.activeElement !== search) {
      event.preventDefault();
      search.focus();
      search.select();
      return;
    }
    if (event.key === "Escape" && document.activeElement === search) {
      search.value = "";
      apply();
      return;
    }
    if (document.activeElement !== search) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      move(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      move(-1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      openCursor();
    }
  });

  /* ---- copy to clipboard -------------------------------------------------- */

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    // file:// pages have no async clipboard; fall back to a detached textarea.
    return new Promise(function (resolve, reject) {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "readonly");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try {
        ok = document.execCommand("copy");
      } catch (err) {
        ok = false;
      }
      document.body.removeChild(area);
      ok ? resolve() : reject(new Error("copy unavailable"));
    });
  }

  cards.addEventListener("click", function (event) {
    var button = event.target.closest(".copy");
    if (!button) return;
    var code = button.parentNode.querySelector("code");
    if (!code) return;
    var original = button.getAttribute("data-label");
    copyText(code.textContent).then(
      function () {
        button.textContent = "copied";
        button.setAttribute("data-copied", "true");
        window.setTimeout(function () {
          button.textContent = original;
          button.removeAttribute("data-copied");
        }, 1400);
      },
      function () {
        button.textContent = "press ⌘C";
        window.setTimeout(function () {
          button.textContent = original;
        }, 1800);
      }
    );
  });

  /* ---- wiring ------------------------------------------------------------- */

  search.addEventListener("input", apply);
  categorySelect.addEventListener("change", apply);
  indexOnly.addEventListener("change", apply);

  // A deep link should survive the initial filter pass.
  apply();
  if (window.location.hash) {
    var target = document.getElementById(window.location.hash.slice(1));
    if (target) target.scrollIntoView({ block: "start" });
  }
})();
