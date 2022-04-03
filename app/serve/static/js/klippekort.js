function handleFormSubmit(event) {
    event.preventDefault();
    
    const data = new FormData(event.target);
    
    const formJSON = Object.fromEntries(data.entries());

    var submit_btn = document.getElementById("submit-button");
    var status_field = document.getElementById("video-post-status");
    submit_btn.disabled = true;
    submit_btn.textContent = "Waiting for download task...";
    if (status_field) {
        status_field.textContent = "";
    }

    var request = new XMLHttpRequest(); 
    request.open('POST', '/api/v1/core/post_link', true);
    request.setRequestHeader('Content-Type', 'application/json; charset=UTF-8'); 
    request.onload = function() {
        if (this.status >= 200 && this.status < 400) {
            var url_segments = this.response.split("/");
            if (url_segments.length > 0) {
                redirectOnProgress(url_segments[url_segments.length - 1]);
            }
        } else {
            console.log("Error when posting video link...");
            submit_btn.disabled = false;
            submit_btn.textContent = "Save for posterity";
            if (status_field) {
                status_field.textContent = this.response;
            }
            console.log(this.response);
        }
    }
    
    request.send(JSON.stringify(formJSON));

}


// if not len(metadata.keys()):
// return abort(404)
// s = metadata["status"]
// if s == STATUS_COMPLETED:
// return ("", 200)
// if s == STATUS_DOWNLOADING:
// return abort(102)
// if s == STATUS_FAILED:
// return ("", 200)
// if s == STATUS_INVALID or s == STATUS_COOKIES:
// return abort(415)
// return abort(500)

function redirectOnProgress(video_id) {
    var request = new XMLHttpRequest(); 
    request.open('GET', '/check_progress/' + video_id, true);
    request.onload = function() {
        if (this.status == 404) {
            setTimeout(() => { redirectOnProgress(video_id); }, 500);
        } else if (this.status == 200 || this.status == 206 || this.status == 415) {
            window.location.href = '/' + video_id;
        } else {
            var submit_btn = document.getElementById("submit-button");
            console.log("Error...");
            submit_btn.disabled = false;
            submit_btn.textContent = "Save for posterity";
            console.log(this.response);
        }
    }
    
    request.send();
}


function redirectOnComplete(video_id) {
    var request = new XMLHttpRequest(); 
    request.open('GET', '/check_progress/' + video_id, true);
    request.onload = function() {
        if (this.status == 200 || this.status == 415) {
            window.location.reload();
        } else {
            setTimeout(() => { redirectOnComplete(video_id); }, 1000);
        }
    }
    
    request.send();
}


const form = document.querySelector('#link-form');
if (form) {
    form.addEventListener('submit', handleFormSubmit);
}
