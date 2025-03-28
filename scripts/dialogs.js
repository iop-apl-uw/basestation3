    var loginCallback = null;

    function testCapsLock(e) {
        if(e.code === "CapsLock"){
            let state = e.getModifierState("CapsLock");
            if (state) $('capLockIndicator').style.display = "inline"; 
            else $('capLockIndicator').style.display       = "none";
        }
    }

    function capsLockOn(e) {
        if (e.code == 'CapsLock' && e.getModifierState("CapsLock") == false)
            $('capLockIndicator').style.display = "inline"; 
        else if (e.code != 'CapsLock' && e.getModifierState("CapsLock") == true)
            $('capLockIndicator').style.display = "inline"; 
        else
            $('capLockIndicator').style.display = "none"; 
    }

    function capsLockOff(e) {
        console.log('up ' + e.code + ' ' + e.getModifierState("CapsLock"));
    }


    const openMessageAsync = async() => {
        return new Promise((resolve) => {
            $('alertOk').onclick = function() { resolve('ok'); }
            $('alertCancel').onclick = function() { resolve('cancel'); }
        });
    }

    function openMessagePopup(content, cancel, callback) {
        $('alertCancel').style.display = cancel ? 'inline-block' : 'none';
        $('alertPopup').style.display = 'inline-block';
        $('alertContents').innerHTML = content;
        (async function() { 
            let state = await openMessageAsync(); 
            $('alertPopup').style.display = 'none';
            if (state == 'ok' && callback) callback();
        })();
    }
    
   
    function openLoginForm(callback, header) {
        $('loginHeader').innerHTML = header ? header : '';
        $('loginForm').style.display = "block";
        if ($('chkHavePilotCode').checked) {
            $('txtCode').style.display = "block";
        }

        $('inpPassword').addEventListener("keydown", capsLockOn);
//        $('inpPassword').addEventListener("keyup", capsLockOff); 
        loginCallback = callback;
    }

    function closeLoginForm() {
        $('loginForm').style.display = "none";
    } 
    function closeRegressionForm() {
        $('regressionForm').style.display = "none";
    } 
    function closeMagcalForm() {
        $('magcalForm').style.display = "none";
    } 

    function closeAboutForm() {
        $('aboutForm').style.display = "none";
    } 
    function openAboutForm() {
        $('aboutForm').style.display = "block";
    } 
    function closeSearchForm() {
        $('searchForm').style.display = "none";
    } 
    function openSearchForm() {
        $('searchForm').style.display = "block";
    } 
    function openMagcalForm() {
        $('magcalForm').style.display = "block";
    } 
    function openRegressionForm() {
        var opts = ['limit=1'];
        if (mission() != '')
            opts.push(mission()) 

        var q = `query/${currGlider}/dive,log_MASS${formatQuery(opts)}`

        fetch(q)
        .then(res => res.text())
        .then(text => {
            try {
                data = JSON.parse(text);
                $('mass').value = data['log_MASS'];
            } catch (error) {
                console.log('openRegressionForm ' + error);
            }
            $('regressionForm').style.display = "block";
        });
    } 

    function submitMagcalForm() {
        var formData = new FormData($('formMagcalForm'));
        var obj = Object.fromEntries(formData);
        var opts = []

        if (mission() != '')
            opts.push(mission());
        if ('softiron' in obj)
            opts.push('softiron=1');

        url = 'magcal/' + currGlider
                        + '/' + obj['dives']
                        + formatQuery(opts);

        console.log(url);
        window.open(url, currGlider + '-magcal');
    }

    function submitRegressionForm() {
        var formData = new FormData($('formRegressionForm'));
        var obj = Object.fromEntries(formData);
        var opts = []

        if (obj['dives'] == '' ||
            obj['depth1'] == '' ||
            obj['depth2'] == '' ||
            obj['initBias'] == '') {
            openMessagePopup('missing required input (dives, min depth, max depth, init bias)', false, null);
            return;
        }

        if (parseFloat(obj['initBias']) == 0) {
            openMessagePopup('zero value for init bias not recommended', false, null);
        } 

        if (mission() != '')
            opts.push(mission());
        if ('ballast' in obj)
            opts.push('ballast=1');
       
        if ('mass' in obj && obj['mass'] != '')
            opts.push('mass=' + obj['mass'])
        if ('density' in obj && obj['density'] != '')
            opts.push('density=' + obj['density'])
        if ('thrust' in obj && obj['thrust'] != '')
            opts.push('thrust=' + obj['thrust'])

        url = 'regress/' + currGlider
                    + '/' + obj['dives']
                    + '/' + obj['depth1']
                    + '/' + obj['depth2']
                    + '/' + obj['initBias']
                    + formatQuery(opts);
                    
        console.log(url);
        window.open(url, currGlider + '-regression');
    }

    function submitLoginForm() {
        var formData = new FormData($('formLoginForm'));
        var json = JSON.stringify(Object.fromEntries(formData));
        fetch('/auth',
        {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: json
        })
        .then(res => res.json())
        .then(d => {
            closeLoginForm();
            if (d['status'] == 'pending') {
                window.location.replace('/setup');
            }
            else if (d['status'] == 'authorized') {
                var txt = 'successfully logged in';
                if ('fails' in d && d['fails'] > 0)
                    txt = txt + `<br>${d['fails']} previous failed attempts`;
                if ('previous' in d) {
                    var date = new Date(Math.floor(d['previous'])*1000).toISOString().replace('T', ' ');
                    txt = txt + `<br>last login attempt ${date}`;
                }
                openMessagePopup(txt, false, loginCallback);
            }
            else {
                openMessagePopup(d['msg'], true, function() { openLoginForm(loginCallback, null); });
            }
        })
        .catch(error => {
            alert(error);
            closeLoginForm();
        });

    } 

    function submitSearchForm() {
        var url;

        var stat = [...$('searchStatus').selectedOptions].map(option => option.value);
        var project = [...$('searchProject').selectedOptions].map(option => option.value);
        var glider = [...$('searchGlider').selectedOptions].map(option => option.value);

        let p = new URLSearchParams();
        if (stat.length > 0)
            p.append("status", stat.join(','));
        if (project.length > 0)
            p.append("mission", project.join(','));
        if (glider.length > 0)
            p.append("gliders", glider.join(','));

        searchURL = window.location.origin + window.location.pathname;
        url = searchURL + '?' + p.toString();
        closeSearchForm();
        window.location.assign(url);
    }

