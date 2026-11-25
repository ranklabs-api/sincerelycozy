(() => {
  function extractAmazonTarget(rawHref) {
    if (!rawHref) return null;
    let url;
    try {
      url = new URL(rawHref, window.location.href);
    } catch {
      return null;
    }
    if (!/^https?:$/i.test(url.protocol)) return null;
    if (!/(^|\.)amazon\.com$/i.test(url.hostname)) return null;

    const asinMatch = url.pathname.match(
      /\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:[/?#]|$)/i
    );
    if (asinMatch) {
      return { asin: asinMatch[1].toUpperCase(), linkUrl: url.href };
    }

    if (/^\/stores\/sincerelycozy(?:\/|$)/i.test(url.pathname)) {
      return { asin: 'storefront', linkUrl: url.href };
    }

    return null;
  }

  function handleAmazonClick(event) {
    if (event.type === 'auxclick' && event.button !== 1) return;
    const anchor = event.target && event.target.closest
      ? event.target.closest('a[href]')
      : null;
    if (!anchor) return;

    const target = extractAmazonTarget(anchor.getAttribute('href') || anchor.href);
    if (!target || typeof window.gtag !== 'function') return;

    window.gtag('event', 'amazon_buy_click', {
      asin: target.asin,
      page_path: window.location.pathname,
      page_location: window.location.href,
      link_url: target.linkUrl,
      transport_type: 'beacon'
    });
  }

  document.addEventListener('click', handleAmazonClick, true);
  document.addEventListener('auxclick', handleAmazonClick, true);
})();
