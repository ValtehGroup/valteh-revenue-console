(function () {
  "use strict";

  const STORAGE_KEY = "valteh-theme";
  function normalizeTheme(value) {
    return value === "dark" ? "dark" : value === "light" ? "light" : null;
  }

  function systemTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function savedTheme() {
    try {
      return normalizeTheme(window.localStorage.getItem(STORAGE_KEY));
    } catch (_error) {
      return null;
    }
  }

  function saveTheme(theme) {
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch (_error) {
      // The theme still works for the current session when storage is unavailable.
    }
  }

  function themeFromStore(data) {
    if (data && data.explicit === true) {
      return normalizeTheme(data.theme);
    }
    return null;
  }

  function applyTheme(theme, persist) {
    const selected = normalizeTheme(theme) || systemTheme();
    document.documentElement.dataset.theme = selected;
    document.cookie = `valteh-theme=${selected}; path=/; max-age=31536000; samesite=lax`;
    if (persist) {
      saveTheme(selected);
    }
    return selected;
  }

  const initialTheme = savedTheme() || systemTheme();
  applyTheme(initialTheme, Boolean(savedTheme()));

  window.dash_clientside = window.dash_clientside || {};
  window.dash_clientside.valtehTheme = {
    toggleTheme: function (nClicks, currentData) {
      const explicitTheme = themeFromStore(currentData) || savedTheme();
      const current = explicitTheme || normalizeTheme(document.documentElement.dataset.theme) || systemTheme();
      if (!nClicks) {
        applyTheme(current, Boolean(explicitTheme));
        return { theme: current, explicit: Boolean(explicitTheme) };
      }
      const next = current === "dark" ? "light" : "dark";
      applyTheme(next, true);
      return { theme: next, explicit: true };
    },
    syncTheme: function (data, _pathname) {
      const explicitTheme = themeFromStore(data) || savedTheme();
      const selected = applyTheme(explicitTheme || systemTheme(), Boolean(explicitTheme));
      const dark = selected === "dark";
      const nextLabel = dark ? "Switch to light theme" : "Switch to dark theme";
      return [dark ? "☾" : "☀", dark ? "Dark" : "Light", nextLabel, nextLabel, String(dark)];
    },
  };
})();
