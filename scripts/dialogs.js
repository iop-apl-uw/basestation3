    var loginCallback = null;

    function openLoginForm(callback) {
        $('loginForm').style.display = "block";
        loginCallback = callback;
    }

    function closeLoginForm() {
        $('loginForm').style.display = "none";
    } 
    function closeRegressionForm() {
        $('regressionForm').style.display = "none";
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
    function openRegressionForm() {
        $('regressionForm').style.display = "block";
    } 

    function submitRegressionForm() {
        var formData = new FormData($('formRegressionForm'));
        console.log(formData);
        var obj = Object.fromEntries(formData);
        console.log(obj);

        window.open('regress/' + currGlider
                    + '/' + obj['dives']
                    + '/' + obj['depth1']
                    + '/' + obj['depth2']
                    + '/' + obj['initBias']
                    + mission()
                    , currGlider + '-regression');
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
        .then(res => res.text())
        .then(text => {
            closeLoginForm();
            console.log(text);
            if (text.includes('failed'))  {
                alert(text);
            }
            else {
                console.log(window.location.pathname);
                console.log(window.location.search);
                if (loginCallback) loginCallback();
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

