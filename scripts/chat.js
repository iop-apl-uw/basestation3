// Make the DIV element draggable:

    function dragElement(elmnt) {
        var pos1 = 0, pos2 = 0, pos3 = 0, pos4 = 0;
        if ($(elmnt.id + "Header")) {
            // if present, the header is where you move the DIV from:
            $(elmnt.id + "Header").onmousedown = dragMouseDown;
        } else {
            // otherwise, move the DIV from anywhere inside the DIV:
            elmnt.onmousedown = dragMouseDown;
        }

        function dragMouseDown(e) {
            e = e || window.event;
            e.preventDefault();
            // get the mouse cursor position at startup:
            pos3 = e.clientX;
            pos4 = e.clientY;
            document.onmouseup = closeDragElement;
            // call a function whenever the cursor moves:
            document.onmousemove = elementDrag;
        }

        function elementDrag(e) {
            e = e || window.event;
            e.preventDefault();
            // calculate the new cursor position:
            pos1 = pos3 - e.clientX;
            pos2 = pos4 - e.clientY;
            pos3 = e.clientX;
            pos4 = e.clientY;
            // set the element's new position:
            elmnt.style.top = (elmnt.offsetTop - pos2) + "px";
            elmnt.style.left = (elmnt.offsetLeft - pos1) + "px";
        }

        function closeDragElement() {
            // stop moving when mouse button is released:
            document.onmouseup = null;
            document.onmousemove = null;
        }
    }

    function chatSend() {
        var formdata = new FormData();
        var message = $('chatInput').value.trim();

        if (!chatHaveAttachment && message == '') 
            return;

        if (chatHaveAttachment) {
            chatHaveAttachment = false;
            formdata.append('attachment', $('attachImage').files[0]);
            $('attachImage').value = null;
            $('chatInput').style.border = '1px solid black';
            console.log('image attached');
        }

        console.log(message);
        formdata.append('message', message);

        for (k of formdata.keys()) {
            console.log(k);
            console.log(formdata.get(k));
        }

        fetch(`/chat/${currGlider}${mission()}`,
        {
            method: 'POST',
            //headers: {
            //    'Content-Type': 'multipart/form-data'
            //},
            body: formdata, // JSON.stringify(json),
        })
        .then(res => res.text())
        .then(text => {
            if (text.includes("authorization failed")) {
                openLoginForm(function() { setupStream(currGlider, 0); chatSend(); } );
                return;
            }
            $('chatInput').value = '';
        })
        .catch(error => {
            alert(error);
        });

    }

    function chatClose() {
        $('chatDiv').style.display = 'none';
    }

    function chatShow() {
        $('chatDiv').style.display = 'block';
    }

    var chatHaveAttachment = false;
    function attachImageChange() {
        $('chatInput').style.border = "1px solid blue";
        chatHaveAttachment = true;
    }
