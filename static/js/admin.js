/* Progressive enhancement for the admin panel. Everything still posts normal forms without JS. */
(function () {
  "use strict";

  // ---- repeatable rows -------------------------------------------------
  document.querySelectorAll(".rep").forEach(function (rep) {
    var add = document.createElement("button");
    add.type = "button";
    add.className = "btn small ghost rep-add";
    add.textContent = "+ " + (rep.dataset.label || "Add another");
    rep.appendChild(add);
    add.addEventListener("click", function () {
      var rows = rep.querySelectorAll(".rep-row");
      var clone = rows[rows.length - 1].cloneNode(true);
      clone.querySelectorAll("input").forEach(function (i) { i.value = ""; });
      rep.insertBefore(clone, add);
      var first = clone.querySelector("input");
      if (first) first.focus();
    });
    rep.addEventListener("click", function (e) {
      if (!e.target.classList.contains("rep-del")) return;
      var rows = rep.querySelectorAll(".rep-row");
      var row = e.target.closest(".rep-row");
      if (rows.length > 1) row.remove();
      else row.querySelectorAll("input").forEach(function (i) { i.value = ""; });
    });
  });

  // ---- rich text editor -----------------------------------------------
  var tools = [
    ["B", "bold", null, "Bold"], ["I", "italic", null, "Italic"], ["U", "underline", null, "Underline"],
    ["H", "formatBlock", "h3", "Heading"], ["¶", "formatBlock", "p", "Paragraph"],
    ["• List", "insertUnorderedList", null, "Bulleted list"], ["1. List", "insertOrderedList", null, "Numbered list"],
    ["Link", "link", null, "Add link"], ["Clear", "removeFormat", null, "Clear formatting"]
  ];
  document.querySelectorAll("textarea.rt").forEach(function (ta) {
    var wrap = document.createElement("div");
    wrap.className = "rte-wrap";
    var bar = document.createElement("div");
    bar.className = "rte-bar";
    var ed = document.createElement("div");
    ed.className = "rte";
    ed.contentEditable = "true";
    ed.innerHTML = ta.value;
    tools.forEach(function (t) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = t[0];
      b.title = t[3];
      b.addEventListener("mousedown", function (e) { e.preventDefault(); });
      b.addEventListener("click", function () {
        ed.focus();
        if (t[1] === "link") {
          var url = prompt("Link address (https://…)");
          if (url) document.execCommand("createLink", false, url);
        } else {
          document.execCommand(t[1], false, t[2]);
        }
      });
      bar.appendChild(b);
    });
    wrap.appendChild(bar);
    wrap.appendChild(ed);
    ta.style.display = "none";
    ta.parentNode.insertBefore(wrap, ta);
    ed.addEventListener("paste", function (e) {  // paste as plain text
      e.preventDefault();
      var text = (e.clipboardData || window.clipboardData).getData("text/plain");
      document.execCommand("insertText", false, text);
    });
    ta.form.addEventListener("submit", function () { ta.value = ed.innerHTML; });
  });

  // ---- custom-field type -> options box --------------------------------
  var typeSel = document.getElementById("cf-type");
  if (typeSel) {
    var box = document.getElementById("cf-options");
    var sync = function () { box.hidden = !(typeSel.value === "select" || typeSel.value === "multiselect"); };
    typeSel.addEventListener("change", sync);
    sync();
  }

  // ---- drag & drop ordering -------------------------------------------
  document.querySelectorAll("ul.sortable").forEach(function (list) {
    var dragging = null;
    var idAttr = list.dataset.idattr || "id";
    var idKey = list.dataset.idkey || "ids";
    list.addEventListener("dragstart", function (e) {
      if (!e.target.closest || !e.target.closest(".grip") && e.target.tagName !== "LI") {
        // only start from the handle or the row itself
      }
      dragging = e.target.closest("li");
      if (dragging) { dragging.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", ""); }
    });
    list.addEventListener("dragover", function (e) {
      if (!dragging) return;
      e.preventDefault();
      var over = e.target.closest("li");
      if (over && over !== dragging) {
        var r = over.getBoundingClientRect();
        list.insertBefore(dragging, e.clientY > r.top + r.height / 2 ? over.nextSibling : over);
      }
    });
    list.addEventListener("dragend", function () {
      if (!dragging) return;
      dragging.classList.remove("dragging");
      dragging = null;
      var ids = Array.prototype.map.call(list.querySelectorAll(":scope > li"), function (li) {
        return li.dataset[idAttr];
      });
      var body = {}; body[idKey] = ids;
      fetch(list.dataset.reorder, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": list.dataset.csrf },
        body: JSON.stringify(body)
      }).then(function (r) { if (!r.ok) location.reload(); }).catch(function () { location.reload(); });
    });
  });

  // ---- confirm before leaving a changed form ----------------------------
  var editForm = document.querySelector("form.editor, form.stack[enctype]");
  if (editForm) {
    var dirty = false;
    editForm.addEventListener("input", function () { dirty = true; });
    editForm.addEventListener("submit", function () { dirty = false; });
    window.addEventListener("beforeunload", function (e) { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
  }
})();
