function handleFormSubmit(event) {
    event.preventDefault();
    
    const data = new FormData(event.target);
    
    const formJSON = Object.fromEntries(data.entries());

    var submit_btn = document.getElementById("submit-button");
    var status_field = document.getElementById("video-post-status");
    var title_field = document.getElementById("title");
    var url_field = document.getElementById("url");
    var cw_field = document.getElementById("content_warning");
    var category_field = document.getElementById("category");
    submit_btn.disabled = true;
    submit_btn_old_text = submit_btn.innerHTML
    submit_btn.innerHTML = "<div uk-spinner></div> Submitting link..."
    if (status_field) {
        status_field.textContent = "";
    }

    var request = new XMLHttpRequest();
    request.open('POST', '/api/v1/core/post_link', true);
    request.setRequestHeader('Content-Type', 'application/json; charset=UTF-8');
    request.onload = function() {
        if (this.status == 201) {
            var url_segments = this.response.split("/");
            if (url_segments.length > 0) {
                redirectOnProgress(url_segments[url_segments.length - 1]);
            }
        } else if (this.status == 202) {
            submit_btn.disabled = false;
            submit_btn.innerHTML = submit_btn_old_text;
            if (status_field) { status_field.innerHTML = '<span class="uk-text-success">' + this.response + '</span>'; }
            if (title_field) { title_field.value = ""; }
            if (url_field) { url_field.value = ""; }
            if (cw_field) { cw_field.value = "default"; }
            if (category_field) { category_field.value = "default"; }
            console.log(this.response);

        } else if (this.status < 200) {
            submit_btn.disabled = false;
            submit_btn.innerHTML = submit_btn_old_text;
            if (status_field) {
                status_field.innerHTML = '<span class="uk-text-danger">Unknown error when contacting server.</span>';
            }
            console.log(this.status);
            console.log(this.response);
        } else if (this.status > 203 && this.status < 500) {
            submit_btn.disabled = false;
            submit_btn.innerHTML = submit_btn_old_text;
            if (status_field) {
                status_field.innerHTML = '<span class="uk-text-primary">' + this.response + '</span>';
            }
            console.log(this.response);
        } else {
            submit_btn.disabled = false;
            submit_btn.innerHTML = submit_btn_old_text;
            if (status_field) {
                status_field.innerHTML = '<span class="uk-text-danger">Unknown error when contacting server</span>';
            }
            console.log(this.response);
        }
    }
    request.onerror = function(err) {
        console.error(err);
        submit_btn.disabled = false;
        submit_btn.innerHTML = submit_btn_old_text;
        if (status_field) {
            status_field.innerHTML = '<span class="uk-text-danger">Unknown error when contacting server.</span>';
        }
        console.log(this.response);
    }
    try {
        request.send(JSON.stringify(formJSON));
    } catch (err) {
        console.error(err);
    }

}


function suggestTitle() {
    var url_field = document.getElementById("url");
    var title_field = document.getElementById("title");
    var suggest_btn = document.getElementById("suggest-button");
    console.log("Asking for title suggestion.");
    if (!url_field || !title_field) {
        return;
    }
    var url = url_field.value;
    if (url.length <= 0) {
        return;
    }



    var suggest_btn_old_text = "";
    if (suggest_btn) {
        suggest_btn.disabled = true;
        suggest_btn_old_text = suggest_btn.innerHTML;
        suggest_btn.innerHTML = "<div uk-spinner='ratio: 0.5'></div> Awaiting suggestion";
    }

    var request = new XMLHttpRequest();
    request.open('POST', '/api/v1/core/title_suggestion', true);
    request.setRequestHeader('Content-Type', 'application/json; charset=UTF-8');
    request.onload = function() {
        if (suggest_btn) {
            suggest_btn.disabled = false;
            suggest_btn.innerHTML = suggest_btn_old_text;
        }
        if (this.status == 200) {
            if (this.response.length > 0) {
                title_field.value = this.response;
                url_field.setCustomValidity("");
            } else if (title_field.value.length == 0) {
                title_field.value = "No title found";
            }
        } else if (this.status == 418 || this.status == 406) {
            url_field.setCustomValidity(this.response);
        } else if (this.status >= 400 && this.status < 500) {
            if (suggest_btn) {
                suggest_btn.classList.add("uk-animation-shake");
            }
            url_field.setCustomValidity("Unknown error when requesting that URL");
            console.log(this.response);
        } else {
            console.log("Unknown error from server when requesting title suggestion.");
        }
        url_field.reportValidity();
    }
    request.onerror = function(err) {
        console.error(err);
        if (suggest_btn) {
            suggest_btn.disabled = false;
            suggest_btn.innerHTML = suggest_btn_old_text;
        }
        return;
    }
    try {
        request.send(JSON.stringify({'url': url}));
    } catch (err) {
        console.error(err);
    }
}


function startDownload(video_id) {
    var dl_btn = document.getElementById("start-download-button");
    var status_field = document.getElementById("video-download-status");
    var dl_old_text = "";
    if (dl_btn) {
        dl_btn.disabled = true;
        dl_old_text = dl_btn.innerHTML
        dl_btn.innerHTML = "<div uk-spinner='ratio: 0.75'></div> Starting task..."
    }
    if (status_field) {
        status_field.textContent = "";
    }

    var request = new XMLHttpRequest();
    request.open('POST', '/api/v1/core/start_download/' + video_id, true);
    request.setRequestHeader('Content-Type', 'application/json; charset=UTF-8');
    request.onload = function() {
        if (this.status == 201) {
            window.location.href = '/' + video_id;
        } else if (this.status >= 400 && this.status < 500) {
            dl_btn.disabled = false;
            dl_btn.innerHTML = dl_old_text;
            if (status_field && this.response.length < 1000) {
                status_field.innerHTML = '<span class="uk-text-danger">' + this.response + '</span>';
            }
        } else {
            dl_btn.disabled = false;
            dl_btn.innerHTML = dl_old_text;
            if (status_field) {
                status_field.innerHTML = '<span class="uk-text-warning">Unknown server error :(</span>';
            }
            console.log(this.status);
        }
    }
    request.onerror = function(err) {
        console.error(err);
        dl_btn.disabled = false;
        dl_btn.innerHTML = dl_old_text;
        if (status_field) {
            status_field.innerHTML = '<span class="uk-text-danger">Unknown error when contacting server.</span>';
        }
        console.log(this.response);
    }
    try {
        request.send("");
    } catch (err) {
        console.error(err);
    }

}

function startProcessing(video_id) {
    var dl_btn = document.getElementById("start-processing-button");
    var status_field = document.getElementById("video-download-status");
    var dl_old_text = "";
    if (dl_btn) {
        dl_btn.disabled = true;
        dl_old_text = dl_btn.innerHTML
        dl_btn.innerHTML = "<div uk-spinner='ratio: 0.75'></div> Starting task..."
    }
    if (status_field) {
        status_field.textContent = "";
    }

    var request = new XMLHttpRequest();
    request.open('POST', '/api/v1/core/start_processing/' + video_id, true);
    request.setRequestHeader('Content-Type', 'application/json; charset=UTF-8');
    request.onload = function() {
        if (this.status == 201) {
            window.location.href = '/' + video_id;
        } else if (this.status >= 400) {
            dl_btn.disabled = false;
            dl_btn.innerHTML = dl_old_text;
            if (status_field) {
                status_field.innerHTML = '<span class="uk-text-danger">' + this.response + '</span>';
            }
            console.log(this.response);
        } else {
            dl_btn.disabled = false;
            dl_btn.innerHTML = dl_old_text;
            if (status_field) {
                status_field.innerHTML = '<span class="uk-text-warning">Unknown server error :(</span>';
            }
            console.log(this.status);
            console.log(this.response);
        }
    }
    request.onerror = function(err) {
        console.error(err);
        dl_btn.disabled = false;
        dl_btn.innerHTML = dl_old_text;
        if (status_field) {
            status_field.innerHTML = '<span class="uk-text-danger">Unknown error when contacting server.</span>';
        }
        console.log(this.response);
    }
    try {
        request.send("");
    } catch (err) {
        console.error(err);
    }

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
    var progress_text = document.getElementById("progress-text");
    var request = new XMLHttpRequest(); 
    request.open('GET', '/check_progress/' + video_id, true);
    request.onload = function() {
        if (this.status == 200 || this.status == 201 || this.status == 415) {
            window.location.reload();
        } else {
            if (this.status == 206 && progress_text) {
                var prog = parseFloat(this.response);
                if (!prog) {
                    prog = 0.0;
                }
                if (prog == 0.0) {
                    progress_text.innerHTML = "<span class='uk-text-small'>Waiting...</span>";
                } else {
                    progress_text.innerHTML = Math.floor(prog * 100.0).toString() + "%";
                }
//                console.log(prog);
            }
            setTimeout(() => { redirectOnComplete(video_id); }, 1000);
        }
    }
    
    request.send();
}


const form = document.querySelector('#link-form');
if (form) {
    form.addEventListener('submit', handleFormSubmit);
}
