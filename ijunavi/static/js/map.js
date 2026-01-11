(function () {
  function normalizeAddress(raw) {
    if (!raw) return "";

    let s = String(raw).trim();

    // ありがちな混入を除去
    s = s.replace(/^■\s*結論\s*[:：]\s*/g, "");
    s = s.replace(/[「」]/g, "");
    s = s.replace(/[（(].*?[）)]/g, ""); // 括弧内を削除（要約等が入っても落ちないように）
    s = s.replace(/の.+$/g, "");         // 「○○市の○○」→「○○市」
    s = s.split(/[、,：:\n]/)[0].trim(); // 余計な説明を切る

    return s.trim();
  }

  function geocodeWithRetry(geocoder, map, address, onSuccess) {
    const candidates = [
      address,
      `${address} 日本`,
      `日本 ${address}`,
    ].filter(Boolean);

    let idx = 0;

    const tryOnce = () => {
      const q = candidates[idx];
      geocoder.geocode({ address: q, region: "JP" }, function (results, status) {
        if (status === "OK" && results && results[0]) {
          onSuccess(results[0], q);
          return;
        }
        idx += 1;
        if (idx < candidates.length) {
          tryOnce();
        } else {
          console.error("Geocode failed:", status, "address=", address, "candidates=", candidates);
        }
      });
    };

    tryOnce();
  }

  function initMap() {
    const mapElement = document.getElementById("result-map");
    if (!mapElement) return;

    const raw = mapElement.dataset.address;
    const address = normalizeAddress(raw);

    const defaultCenter = { lat: 35.681236, lng: 139.767125 };
    const map = new google.maps.Map(mapElement, {
      center: defaultCenter,
      zoom: 5,
      mapTypeControl: false,
      streetViewControl: false,
    });

    if (!address) {
      console.warn("住所が空です (data-address がありません)");
      return;
    }

    const geocoder = new google.maps.Geocoder();

    geocodeWithRetry(geocoder, map, address, function (result, usedQuery) {
      const loc = result.geometry.location;

      map.setCenter(loc);
      map.setZoom(12);

      new google.maps.Marker({
        map: map,
        position: loc,
        title: usedQuery,
      });
    });
  }

  window.initMap = initMap;
})();
