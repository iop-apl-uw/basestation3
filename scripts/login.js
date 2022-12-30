    function openLoginForm() {
        $('loginForm').style.display = "block";
    }

    function closeLoginForm() {
        $('loginForm').style.display = "none";
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
            if (text.includes('failed')) 
                alert(text);
            else {
                console.log(text);
                window.location.reload();
            }
            closeLoginForm();
        })
        .catch(error => {
            alert(error);
            closeLoginForm();
        });

    } 
