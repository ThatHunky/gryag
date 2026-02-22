package tools

// RequestMediaBase64Key is the context key for the current request's media (base64) when the user sent an attachment.
// Used by edit_image with use_context_image to get the image from the current message.
var RequestMediaBase64Key = &requestMediaKeyType{}

type requestMediaKeyType struct{}