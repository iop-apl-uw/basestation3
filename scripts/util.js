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
