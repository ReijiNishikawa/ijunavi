(function () {
  function initMap() {
    const mapElement = document.getElementById("result-map");
    if (!mapElement) return;

    const address = mapElement.dataset.address;
    const defaultCenter = { lat: 35.681236, lng: 139.767125 };

    const map = new google.maps.Map(mapElement, {
      center: defaultCenter,
      zoom: 5,
    });

    if (!address) {
      console.warn("住所が指定されていません");
      return;
    }

    const geocoder = new google.maps.Geocoder();

    geocoder.geocode({ address: address }, function (results, status) {
      if (status === "OK" && results[0]) {
        const loc = results[0].geometry.location;
        map.setCenter(loc);
        map.setZoom(11);

        new google.maps.Marker({
          map: map,
          position: loc,
          title: address,
        });
      } else {
        console.error("Geocode failed: " + status);
      }
    });
  }

  // Google Maps APIの callback=initMap から呼ばれるようにグローバルへ
  window.initMap = initMap;
})();
