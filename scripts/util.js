function $(x) {
    return document.getElementById(x)
}

Number.prototype.zeroPad = function() {
    let t = '' + this;
    if (t.length > 2 && this > 0)
        return t;
    else if (t.length > 3 && this < 0)
        return t;

    if (this > 0)
        return ('0'+this).slice(-2);
    else
        return ('-0'+this).slice(-2);
}

function formatQuery(params) {
    var q = '';
    if (params.length) {
        q = '?' 
        for (i = 0 ; i < params.length ; i++) {
            if (params[i].charAt(0) == '?' || params[i].charAt(0) == '&')
                q = q + params[i].slice(1);
            else
                q = q + params[i];
            if (i < params.length - 1)
                q = q + '&';
        }
    }

    return q; 
}

function setInnerHTML(elm, html) {
    elm.innerHTML = html;

    Array.from(elm.querySelectorAll("script"))
      .forEach( oldScriptEl => {
        const newScriptEl = document.createElement("script");

        Array.from(oldScriptEl.attributes).forEach( attr => {
            newScriptEl.setAttribute(attr.name, attr.value)
        });

        const scriptText = document.createTextNode(oldScriptEl.innerHTML);
        newScriptEl.appendChild(scriptText);

        oldScriptEl.parentNode.replaceChild(newScriptEl, oldScriptEl);
    });
}

function bearing(pt1, pt2) {
    var lat2 = pt2.lat*Math.PI/180;
    var lat1 = pt1.lat*Math.PI/180;
    var dLat = (lat2 - lat1);
    var dLon = (pt2.lon-pt1.lon)*Math.PI/180;
    var y = Math.sin(dLon) * Math.cos(lat2);
    var x = Math.cos(lat1)*Math.sin(lat2) -
            Math.sin(lat1)*Math.cos(lat2)*Math.cos(dLon);
    var brng = (Math.atan2(y, x)*180/Math.PI + 360) % 360;

    return brng;
}

function haversine(pt0, pt1) {
    var lat0, lon0, lat1, lon1;
    var sdlat_2, sdlon_2;
    var a;
    const R = 6378137.0;
    const DTR = 1.745329251994330e-02;

    lat0 = pt0.lat*DTR;
    lat1 = pt1.lat*DTR;
    lon0 = pt0.lon*DTR;
    lon1 = pt1.lon*DTR;

    sdlat_2 = Math.sin(0.5*(lat0 - lat1));
    sdlon_2 = Math.sin(0.5*(lon0 - lon1));

    a = sdlat_2*sdlat_2 + Math.cos(lat0)*Math.cos(lat1)*sdlon_2*sdlon_2;
    if (a >= 1 || a <= 0) {
        return 0;
    }

    return 2.0*R*Math.asin(Math.sqrt(a));
}

function reckon(pt, range, az) 
{
    const DTR = 1.745329251994330e-02;
    const phi1 = pt[0]*DTR;
    const lam1 = pt[1]*DTR;
    const del  = range / 6378137;
    az = az*DTR;
    console.log(phi1, lam1, del); 
    const phi2 = Math.asin( Math.sin(phi1)*Math.cos(del) +
                          Math.cos(phi1)*Math.sin(del)*Math.cos(az) );
    console.log(phi2);
    const lam2 = lam1 + Math.atan2(Math.sin(az)*Math.sin(del)*Math.cos(phi1),
                               Math.cos(del)-Math.sin(phi1)*Math.sin(phi2));

   
    return [phi2/DTR, lam2/DTR];
/*
                const MPD = 111120.0;
                var pt2 = [0,0];

                pt2[0] = pt[0] + range*Math.cos(az*Math.PI/180.0)/MPD;
                pt2[1] = pt[1] + range*Math.sin(az*Math.PI/180.0)/(MPD*Math.cos(pt[0]*Math.PI/180));
                return pt2;
*/
}

function formatDate(d) {
    let yr  = d.getUTCFullYear() - 2000;
    let mon = d.getUTCMonth() + 1;
    let day = d.getUTCDate();
    let h   = d.getUTCHours();
    let m   = d.getUTCMinutes();

    if (day < 10) day = "0" + day;
    if (mon < 10) mon = "0" + mon; 
    if (h < 10) h = "0" + h;
    if (m < 10) m = "0" + m;

    return yr + '-' + mon + '-' + day + ' ' + h + ':' + m;
}

function formatPos(ddmm) {
    var deg = Math.trunc(ddmm/100);
    var min = Math.abs(ddmm - deg*100);
    var zero = min < 10 ? '0' : '';
    return (deg + '&deg;' + zero + min.toFixed(3) + '&prime;');
}

function ddmm2dd(ddmm) {
    var deg = Math.trunc(ddmm/100);
    var min = ddmm - deg*100;

    return deg + min/60;
}

function dd2ddmm(dd) {
    var deg = Math.trunc(dd);
    var min = (dd - deg)*60;
    
    return deg*100 + min;
}

function positionFix(lat, lon, t) {
    var fix =   { 
                    pt: {
                        lat: lat, 
                        lon: lon,
                    },

                    t: t,
                };

    return fix;
}

function createCookie(name,value,days) {
    if (days) {
        var date = new Date();
        date.setTime(date.getTime()+(days*24*60*60*1000));
        var expires = "; expires="+date.toGMTString();
    }
    else var expires = "";
    document.cookie = name+"="+value+expires+"; path=/";
}

function readCookie(name) {
    var nameEQ = name + "=";
    var ca = document.cookie.split(';');
    for(var i=0;i < ca.length;i++) {
        var c = ca[i];
        while (c.charAt(0)==' ') c = c.substring(1,c.length);
        if (c.indexOf(nameEQ) == 0) return c.substring(nameEQ.length,c.length);
    }
    return null;
}

function eraseCookie(name) {
    createCookie(name,"",-1);
}

function beep() {
    var snd = new Audio("data:audio/wav;base64,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qJrx4KOQjahZxWbcZgztj2c49nKmkId44S71j0c8eV9yDK6uPRzx5X18eDvjvQ6yKo9ZSS6l//8elePK/Lf//IInrOF/FvDoADYAGBMGb7FtErm5MXMlmPAJQVgWta7Zx2go+8xJ0UiCb8LHHdftWyLJE0QIAIsI+UbXu67dZMjmgDGCGl1H+vpF4NSDckSIkk7Vd+sxEhBQMRU8j/12UIRhzSaUdQ+rQU5kGeFxm+hb1oh6pWWmv3uvmReDl0UnvtapVaIzo1jZbf/pD6ElLqSX+rUmOQNpJFa/r+sa4e/pBlAABoAAAAA3CUgShLdGIxsY7AUABPRrgCABdDuQ5GC7DqPQCgbbJUAoRSUj+NIEig0YfyWUho1VBBBA//uQZB4ABZx5zfMakeAAAAmwAAAAF5F3P0w9GtAAACfAAAAAwLhMDmAYWMgVEG1U0FIGCBgXBXAtfMH10000EEEEEECUBYln03TTTdNBDZopopYvrTTdNa325mImNg3TTPV9q3pmY0xoO6bv3r00y+IDGid/9aaaZTGMuj9mpu9Mpio1dXrr5HERTZSmqU36A3CumzN/9Robv/Xx4v9ijkSRSNLQhAWumap82WRSBUqXStV/YcS+XVLnSS+WLDroqArFkMEsAS+eWmrUzrO0oEmE40RlMZ5+ODIkAyKAGUwZ3mVKmcamcJnMW26MRPgUw6j+LkhyHGVGYjSUUKNpuJUQoOIAyDvEyG8S5yfK6dhZc0Tx1KI/gviKL6qvvFs1+bWtaz58uUNnryq6kt5RzOCkPWlVqVX2a/EEBUdU1KrXLf40GoiiFXK///qpoiDXrOgqDR38JB0bw7SoL+ZB9o1RCkQjQ2CBYZKd/+VJxZRRZlqSkKiws0WFxUyCwsKiMy7hUVFhIaCrNQsKkTIsLivwKKigsj8XYlwt/WKi2N4d//uQRCSAAjURNIHpMZBGYiaQPSYyAAABLAAAAAAAACWAAAAApUF/Mg+0aohSIRobBAsMlO//Kk4soosy1JSFRYWaLC4qZBYWFRGZdwqKiwkNBVmoWFSJkWFxX4FFRQWR+LsS4W/rFRb/////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////VEFHAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAU291bmRib3kuZGUAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMjAwNGh0dHA6Ly93d3cuc291bmRib3kuZGUAAAAAAAAAACU=");
              // this.onchange();
    snd.play();
}

const multiSelectWithoutCtrl = ( elem ) => {
  
  let options = elem.querySelectorAll(`option`);
  
  options.forEach(function (element) {
      element.addEventListener("mousedown", 
          function (e) {
              e.preventDefault();
              // element.parentElement.focus();
              this.selected = !this.selected;
              elem.onchange();
              return false;
          }, false );
  });

}
