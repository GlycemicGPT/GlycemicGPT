// ZAP HttpSender script: CSRF Token Injector
//
// GlycemicGPT uses header-based CSRF protection. The csrf_token is set as a
// cookie, and state-changing requests must include its value in the
// X-CSRF-Token header. ZAP's built-in anti-CSRF handling only works for
// form-based tokens, so this script bridges the gap by copying the cookie
// value to the header on every outgoing request.

function sendingRequest(msg, initiator, helper) {
    var cookieHeader = msg.getRequestHeader().getHeader("Cookie");
    if (cookieHeader !== null) {
        var match = cookieHeader.match(/csrf_token=([^;\s]+)/);
        if (match && match[1]) {
            msg.getRequestHeader().setHeader("X-CSRF-Token", match[1]);
        }
    }
}

function responseReceived(msg, initiator, helper) {
    // ZAP's cookie jar automatically captures Set-Cookie headers.
    // The next sendingRequest call will pick up any rotated csrf_token.
}
