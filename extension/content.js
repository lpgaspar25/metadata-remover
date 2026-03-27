// Content Script — Media Scanner
// Detects all images and videos on the current page

(function () {
  const IMAGE_EXTS = /\.(jpg|jpeg|png|webp|gif|bmp|tiff|heic|avif|svg)(\?|$|#)/i;
  const VIDEO_EXTS = /\.(mp4|mov|avi|mkv|m4v|wmv|webm|3gp|flv)(\?|$|#)/i;
  const SKIP_PATTERNS = /1x1|pixel|spacer|blank|tracking|beacon|\.svg|emoji|avatar_default|data:image\/svg/i;
  const MIN_SIZE = 40; // Minimum dimension to include

  function resolveUrl(href) {
    if (!href || typeof href !== "string") return null;
    href = href.trim();
    if (href.startsWith("data:") && href.length < 200) return null;
    if (href.startsWith("data:image/svg")) return null;
    if (href === "about:blank" || href === "#") return null;
    try {
      return new URL(href, document.baseURI).href;
    } catch {
      return null;
    }
  }

  function getExtension(url) {
    try {
      const path = new URL(url).pathname;
      const match = path.match(/\.(\w+)$/);
      return match ? match[1].toLowerCase() : "";
    } catch {
      return "";
    }
  }

  function getMediaType(url) {
    if (VIDEO_EXTS.test(url)) return "video";
    if (IMAGE_EXTS.test(url)) return "image";
    // Check common CDN patterns
    if (/video/i.test(url)) return "video";
    return "image";
  }

  function parseSrcset(srcset) {
    if (!srcset) return [];
    const urls = [];
    for (const part of srcset.split(",")) {
      const pieces = part.trim().split(/\s+/);
      if (pieces[0]) {
        const url = resolveUrl(pieces[0]);
        if (url) urls.push(url);
      }
    }
    return urls;
  }

  function scanPage() {
    const seen = new Set();
    const results = [];

    function addMedia(url, type, source, width, height, alt) {
      if (!url || seen.has(url)) return;
      if (SKIP_PATTERNS.test(url)) return;
      seen.add(url);
      results.push({
        url,
        type: type || getMediaType(url),
        source: source || "unknown",
        width: width || 0,
        height: height || 0,
        alt: alt || "",
        extension: getExtension(url),
      });
    }

    // 1. <img> tags
    document.querySelectorAll("img").forEach((img) => {
      const src = resolveUrl(img.src || img.getAttribute("data-src") || img.getAttribute("data-original") || img.getAttribute("data-lazy-src"));
      const w = img.naturalWidth || img.width || 0;
      const h = img.naturalHeight || img.height || 0;
      if (src && (w >= MIN_SIZE || h >= MIN_SIZE || (!w && !h))) {
        addMedia(src, "image", "img", w, h, img.alt);
      }
      // srcset
      const srcset = img.getAttribute("srcset");
      if (srcset) {
        parseSrcset(srcset).forEach((u) => addMedia(u, "image", "srcset", 0, 0, img.alt));
      }
    });

    // 2. <video> tags
    document.querySelectorAll("video").forEach((vid) => {
      const src = resolveUrl(vid.src || vid.getAttribute("data-src"));
      if (src) {
        addMedia(src, "video", "video", vid.videoWidth || 0, vid.videoHeight || 0);
      }
      // poster
      const poster = resolveUrl(vid.poster);
      if (poster) addMedia(poster, "image", "poster", 0, 0);
    });

    // 3. <source> tags
    document.querySelectorAll("source").forEach((s) => {
      const src = resolveUrl(s.src);
      if (src) {
        const parent = s.parentElement?.tagName;
        const type = parent === "VIDEO" ? "video" : "image";
        addMedia(src, type, "source", 0, 0);
      }
      const srcset = s.getAttribute("srcset");
      if (srcset) {
        parseSrcset(srcset).forEach((u) => addMedia(u, "image", "srcset"));
      }
    });

    // 4. <picture> > <source>
    document.querySelectorAll("picture source").forEach((s) => {
      const srcset = s.getAttribute("srcset");
      if (srcset) {
        parseSrcset(srcset).forEach((u) => addMedia(u, "image", "picture"));
      }
    });

    // 5. CSS background-image
    document.querySelectorAll("*").forEach((el) => {
      try {
        const bg = getComputedStyle(el).backgroundImage;
        if (bg && bg !== "none") {
          const matches = bg.matchAll(/url\(["']?(.*?)["']?\)/gi);
          for (const m of matches) {
            const url = resolveUrl(m[1]);
            if (url && !url.startsWith("data:")) {
              addMedia(url, "image", "bg-css", 0, 0);
            }
          }
        }
      } catch {}
    });

    // 6. Meta tags (og:image, og:video, twitter:image)
    document.querySelectorAll('meta[property^="og:"], meta[name^="twitter:"]').forEach((meta) => {
      const prop = meta.getAttribute("property") || meta.getAttribute("name") || "";
      const content = meta.getAttribute("content");
      if (!content) return;
      if (prop.includes("image")) {
        addMedia(resolveUrl(content), "image", prop);
      } else if (prop.includes("video")) {
        addMedia(resolveUrl(content), "video", prop);
      }
    });

    // 7. Link icons
    document.querySelectorAll('link[rel*="icon"]').forEach((link) => {
      const href = resolveUrl(link.href);
      if (href) addMedia(href, "image", "favicon", 0, 0);
    });

    // 8. Links to media files
    document.querySelectorAll("a[href]").forEach((a) => {
      const href = resolveUrl(a.href);
      if (href && (IMAGE_EXTS.test(href) || VIDEO_EXTS.test(href))) {
        addMedia(href, getMediaType(href), "link", 0, 0);
      }
    });

    return results;
  }

  // Listen for scan requests from popup
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.action === "scanMedia") {
      const media = scanPage();
      sendResponse({ media });
    }
    return true;
  });
})();
