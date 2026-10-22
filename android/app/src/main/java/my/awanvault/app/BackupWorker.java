package my.awanvault.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import androidx.documentfile.provider.DocumentFile;
import androidx.work.*;
import java.io.InputStream;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.TimeUnit;

public final class BackupWorker extends Worker {
    private static final Object SCAN_LOCK = new Object();
    public BackupWorker(Context context, WorkerParameters parameters) { super(context, parameters); }
    static SharedPreferences prefs(Context c) { return c.getSharedPreferences("settings", 0); }
    static Constraints constraints(Context c) {
        SharedPreferences p = prefs(c);
        return new Constraints.Builder().setRequiredNetworkType(p.getBoolean("unmetered", true) ? NetworkType.UNMETERED : NetworkType.CONNECTED)
            .setRequiresCharging(p.getBoolean("charging", false)).setRequiresBatteryNotLow(true).build();
    }
    static void schedule(Context c) {
        WorkManager wm = WorkManager.getInstance(c);
        if (!prefs(c).getBoolean("enabled", false)) { wm.cancelAllWorkByTag("awanvault-backup"); return; }
        PeriodicWorkRequest job = new PeriodicWorkRequest.Builder(BackupWorker.class, 1, TimeUnit.HOURS)
            .setConstraints(constraints(c)).setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .addTag("awanvault-backup").build();
        wm.enqueueUniquePeriodicWork("periodic-backup", ExistingPeriodicWorkPolicy.UPDATE, job);
    }
    static void now(Context c) {
        OneTimeWorkRequest job = new OneTimeWorkRequest.Builder(BackupWorker.class).setConstraints(constraints(c))
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).addTag("awanvault-backup").build();
        WorkManager.getInstance(c).enqueueUniqueWork("manual-backup", ExistingWorkPolicy.KEEP, job);
    }
    private void note(String text) { prefs(getApplicationContext()).edit().putString("last_status", text).apply(); }
    private boolean cancelled() { return isStopped() || !prefs(getApplicationContext()).getBoolean("enabled", false); }
    private static String hex(byte[] bytes) { StringBuilder b = new StringBuilder(); for (byte value : bytes) b.append(String.format(Locale.ROOT, "%02x", value & 255)); return b.toString(); }
    private static String hash(String text) throws Exception { return hex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(java.nio.charset.StandardCharsets.UTF_8))); }
    private boolean selected(DocumentFile file, SharedPreferences p) {
        String type = file.getType(), name = file.getName();
        if (type != null && type.startsWith("image/")) return p.getBoolean("photos", true);
        if (!p.getBoolean("documents", true)) return false;
        String extension = name == null ? "" : name.substring(name.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
        return (type != null && (type.startsWith("text/") || type.equals("application/pdf"))) ||
            Arrays.asList("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv", "rtf", "odt", "ods", "odp", "md", "json").contains(extension);
    }
    private String signature(DocumentFile file) throws Exception {
        if (file.lastModified() > 0) return file.lastModified() + ":" + file.length();
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = getApplicationContext().getContentResolver().openInputStream(file.getUri())) {
            if (input == null) throw new java.io.IOException("File unavailable");
            byte[] buffer = new byte[65536]; long total = 0; int count;
            while ((count = input.read(buffer)) != -1) { total += count; if (total > Api.MAX_FILE || cancelled()) throw new java.io.IOException("Stopped or oversized file"); digest.update(buffer, 0, count); }
        }
        return hex(digest.digest());
    }
    private static final class Entry {
        final DocumentFile file; final String relative; final String root;
        Entry(DocumentFile file, String relative, String root) { this.file = file; this.relative = relative; this.root = root; }
    }
    @Override public Result doWork() {
        synchronized (SCAN_LOCK) {
            Context c = getApplicationContext(); SharedPreferences p = prefs(c);
            if (cancelled()) return Result.success();
            long started = android.os.SystemClock.elapsedRealtime(); int uploaded = 0, skipped = 0, unavailable = 0;
            try {
                String token = TokenStore.read(c), base = p.getString("server", "");
                if (token == null || base.isEmpty()) { note("Sign in to start backing up."); return Result.failure(); }
                // Check authorization before using a cached 'already uploaded' decision.
                Api.execute(new okhttp3.Request.Builder().url(base + "/api/status").header("Authorization", "Bearer " + token).build());
                SharedPreferences seen = c.getSharedPreferences("uploaded", 0);
                ArrayDeque<Entry> queue = new ArrayDeque<>();
                for (String uri : new HashSet<>(p.getStringSet("folders", Collections.emptySet()))) {
                    DocumentFile root = DocumentFile.fromTreeUri(c, Uri.parse(uri));
                    if (root == null || !root.canRead()) { unavailable++; continue; }
                    queue.add(new Entry(root, root.getName() == null ? "Folder" : root.getName(), uri));
                }
                Set<String> visited = new HashSet<>();
                while (!queue.isEmpty()) {
                    if (cancelled()) { note("Backup paused. Originals retained."); return Result.success(); }
                    if (android.os.SystemClock.elapsedRealtime() - started > 180000 || uploaded >= 25) {
                        note(uploaded + " uploaded in this batch. More work scheduled."); return Result.retry();
                    }
                    Entry e = queue.removeFirst(); DocumentFile file = e.file;
                    if (!visited.add(file.getUri().toString())) continue;
                    if (!file.canRead()) { unavailable++; continue; }
                    if (file.isDirectory()) {
                        for (DocumentFile child : file.listFiles()) queue.addLast(new Entry(child, e.relative + "/" + child.getName(), e.root));
                        continue;
                    }
                    if (!file.isFile() || !selected(file, p)) continue;
                    if (file.length() > Api.MAX_FILE) { skipped++; continue; }
                    String cacheKey = hash(base + "|" + e.root + "|" + file.getUri());
                    String signature = signature(file);
                    if (signature.equals(seen.getString(cacheKey, null))) continue;
                    String name = file.getName(); if (name == null) { skipped++; continue; }
                    String source = "Android/" + hash(e.root).substring(0, 12) + "/" + e.relative.substring(0, e.relative.lastIndexOf('/'));
                    org.json.JSONObject result;
                    try {
                        result = Api.upload(c, base, token, file.getUri(), name, source, file.getType() == null ? "application/octet-stream" : file.getType(), file.length());
                    } catch (Api.ApiException failure) {
                        if (failure.status == 400 || failure.status == 413) { skipped++; continue; }
                        throw failure;
                    }
                    if (!result.optBoolean("recovery_verified_at_upload", false)) throw new java.io.IOException("Recovery copy not verified");
                    if (signature.equals(signature(file))) seen.edit().putString(cacheKey, signature).commit();
                    uploaded++; note(uploaded + " files backed up in this run. Originals retained.");
                }
                note("Last scan: " + new java.text.SimpleDateFormat("dd MMM HH:mm", Locale.getDefault()).format(new Date()) +
                    " • " + uploaded + " uploaded • " + skipped + " oversized/skipped • " + unavailable + " inaccessible folders/files.");
                return Result.success();
            } catch (Api.ApiException e) {
                if (e.status == 401 || e.status == 403) { p.edit().putBoolean("enabled", false).apply(); note("Access expired or revoked. Sign in again."); schedule(c); return Result.failure(); }
                if (e.status == 400 || e.status == 413) { note("A file was rejected: " + e.getMessage() + ". Review the selected folders."); return Result.failure(); }
                note("Server unavailable. Will retry; originals retained."); return Result.retry();
            } catch (SecurityException e) {
                note("Folder permission lost. Choose your folders again."); return Result.failure();
            } catch (Exception e) {
                note("Backup interrupted. Will retry; originals retained."); return Result.retry();
            }
        }
    }
}
