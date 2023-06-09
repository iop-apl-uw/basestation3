    var loginCallback = null;

    function openLoginForm(callback) {
        $('loginForm').style.display = "block";
        loginCallback = callback;
    }

    function closeLoginForm() {
        $('loginForm').style.display = "none";
    } 

    function closeAboutForm() {
        $('aboutForm').style.display = "none";
    } 
    function openAboutForm() {
        $('aboutForm').style.display = "block";
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
