package my.awanvault.app;

import android.content.Context;
import android.net.Uri;
import android.util.Base64;
import org.json.JSONObject;
import java.io.IOException;
import java.io.InputStream;
import java.util.concurrent.TimeUnit;
import okhttp3.*;
import okio.BufferedSink;

final class Api {
    static final long MAX_FILE = 64L * 1024 * 1024;
    static final OkHttpClient HTTP = new OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS).readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(120, TimeUnit.SECONDS).callTimeout(4, TimeUnit.MINUTES)
        .followRedirects(false).followSslRedirects(false).build();
    static final MediaType JSON = MediaType.get("application/json; charset=utf-8");
    static String validateServer(String input) {
        HttpUrl url = HttpUrl.parse(input.trim());
        if (url == null || !url.isHttps() || !url.username().isEmpty() || !url.password().isEmpty()
            || url.query() != null || url.fragment() != null || !url.encodedPath().equals("/"))
            throw new IllegalArgumentException("Enter an HTTPS server address without a path or credentials.");
        String normalized = url.toString();
        return normalized.substring(0, normalized.length() - 1);
    }
    static JSONObject login(String base, String username, String password, String code) throws Exception {
        JSONObject body = new JSONObject().put("username", username).put("password", password).put("code", code);
        Request request = new Request.Builder().url(base + "/api/auth/device-login")
            .post(RequestBody.create(body.toString(), JSON)).build();
        return execute(request);
    }
    static JSONObject execute(Request request) throws Exception {
        try (Response response = HTTP.newCall(request).execute()) {
            String text = response.body() == null ? "{}" : response.body().string();
            if (!response.isSuccessful()) {
                String message = "Server returned " + response.code();
                try { message = new JSONObject(text).optString("detail", message); } catch (Exception ignored) {}
                throw new ApiException(response.code(), message);
            }
            return new JSONObject(text);
        }
    }
    static void logout(String base, String token) throws Exception {
        execute(new Request.Builder().url(base + "/api/auth/logout").header("Authorization", "Bearer " + token)
            .post(RequestBody.create("{}", JSON)).build());
    }
    static JSONObject upload(Context context, String base, String token, Uri uri, String name, String source, String type, long size) throws Exception {
        JSONObject metadata = new JSONObject().put("name", name).put("source", source).put("media_type", type);
        String encoded = Base64.encodeToString(metadata.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8), Base64.NO_WRAP);
        RequestBody content = new RequestBody() {
            @Override public MediaType contentType() { return MediaType.get("application/octet-stream"); }
            @Override public long contentLength() { return size > 0 ? size : -1; }
            @Override public void writeTo(BufferedSink sink) throws IOException {
                try (InputStream stream = context.getContentResolver().openInputStream(uri)) {
                    if (stream == null) throw new IOException("File unavailable");
                    byte[] buffer = new byte[65536]; long count = 0; int read;
                    while ((read = stream.read(buffer)) != -1) {
                        count += read;
                        if (count > MAX_FILE) throw new IOException("64 MiB file limit exceeded");
                        sink.write(buffer, 0, read);
                    }
                }
            }
        };
        return execute(new Request.Builder().url(base + "/api/files")
            .header("Authorization", "Bearer " + token).header("X-File-Metadata", encoded).put(content).build());
    }
    static class ApiException extends IOException {
        final int status;
        ApiException(int status, String message) { super(message); this.status = status; }
    }
}
