package my.awanvault.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.View;
import android.view.WindowManager;
import android.widget.*;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private LinearLayout page;
    private TextView message;
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final int green = Color.rgb(28, 85, 68), ink = Color.rgb(25, 55, 47), muted = Color.rgb(111, 128, 117);
    private SharedPreferences prefs() { return BackupWorker.prefs(this); }
    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            if (message != null) message.setText(prefs().getString("last_status", "Ready. Choose folders and enable backup."));
            handler.postDelayed(this, 3000);
        }
    };
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE);
        try { if (TokenStore.read(this) == null) loginPage(); else homePage(); }
        catch (Exception e) { TokenStore.clear(this); loginPage(); }
    }
    @Override protected void onResume() { super.onResume(); handler.post(refresh); }
    @Override protected void onPause() { handler.removeCallbacks(refresh); super.onPause(); }
    @Override protected void onDestroy() { handler.removeCallbacksAndMessages(null); io.shutdown(); super.onDestroy(); }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private void base() {
        message = null;
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true); scroll.setBackgroundColor(Color.rgb(246,247,243));
        page = new LinearLayout(this); page.setOrientation(LinearLayout.VERTICAL); page.setPadding(dp(25), dp(30), dp(25), dp(30));
        scroll.addView(page); setContentView(scroll);
        scroll.setOnApplyWindowInsetsListener((v, insets) -> {
            v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        text("▧  AwanVault", 27, ink, true); text("PERSONAL BACKUP · BETA", 10, muted, true); space(28);
    }
    private void space(int size) { View v = new View(this); page.addView(v, new LinearLayout.LayoutParams(1, dp(size))); }
    private TextView text(String value, int size, int color, boolean bold) {
        TextView t = new TextView(this); t.setText(value); t.setTextSize(size); t.setTextColor(color); t.setPadding(0,dp(5),0,dp(5));
        if (bold) t.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        page.addView(t); return t;
    }
    private EditText input(String hint, int type) {
        EditText edit = new EditText(this); edit.setHint(hint); edit.setTextSize(15); edit.setInputType(type); edit.setSingleLine(true);
        edit.setPadding(dp(14),dp(13),dp(14),dp(13));
        GradientDrawable bg = new GradientDrawable(); bg.setColor(Color.WHITE); bg.setCornerRadius(dp(8)); bg.setStroke(dp(1), Color.rgb(220,229,219)); edit.setBackground(bg);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1,-2); params.setMargins(0,dp(7),0,dp(7)); page.addView(edit,params); return edit;
    }
    private Button button(String label, boolean primary, View.OnClickListener action) {
        Button b = new Button(this); b.setText(label); b.setAllCaps(false); b.setTextSize(14); b.setTextColor(primary ? Color.WHITE : green);
        GradientDrawable bg = new GradientDrawable(); bg.setColor(primary ? green : Color.WHITE); bg.setCornerRadius(dp(9)); if (!primary) bg.setStroke(dp(1),Color.rgb(220,229,219));
        b.setBackground(bg); b.setPadding(dp(12),dp(12),dp(12),dp(12));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1,dp(52)); params.setMargins(0,dp(9),0,0); page.addView(b,params); b.setOnClickListener(action); return b;
    }
    private CheckBox option(String title, String key, boolean fallback) {
        CheckBox box = new CheckBox(this); box.setText(title); box.setTextSize(14); box.setTextColor(ink); box.setChecked(prefs().getBoolean(key,fallback)); page.addView(box);
        box.setOnCheckedChangeListener((b, checked) -> { prefs().edit().putBoolean(key,checked).apply(); BackupWorker.schedule(this); }); return box;
    }
    private void toast(String text) { Toast.makeText(this,text,Toast.LENGTH_LONG).show(); }
    private void loginPage() {
        base(); text("Your files. A way back.",30,ink,true);
        text("Connect to your private AwanVault server. Use the AwanVault password and authenticator, separate from Telegram.",14,muted,false); space(15);
        EditText server = input("https://vault.your-domain.com",InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        server.setText(prefs().getString("server",""));
        EditText username = input("Username",InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        EditText password = input("Password",InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        EditText code = input("6-digit authenticator code",InputType.TYPE_CLASS_NUMBER);
        button("Connect securely  ↗",true,view -> {
            final String base;
            try { base = Api.validateServer(server.getText().toString()); } catch (Exception e) { toast(e.getMessage()); return; }
            String user = username.getText().toString(), pass = password.getText().toString(), otp = code.getText().toString();
            if (!otp.matches("[0-9]{6}")) { toast("Enter your six-digit authenticator code."); return; }
            view.setEnabled(false);
            io.execute(() -> {
                try {
                    org.json.JSONObject result = Api.login(base,user,pass,otp);
                    TokenStore.save(this,result.getString("token"));
                    prefs().edit().putString("server",base).putBoolean("enabled",false).apply();
                    runOnUiThread(() -> { if (!isDestroyed()) { password.setText(""); code.setText(""); homePage(); } });
                } catch (Exception e) { runOnUiThread(() -> { if (!isDestroyed()) { view.setEnabled(true); toast(e.getMessage() == null ? "Connection failed" : e.getMessage()); } }); }
            });
        });
        space(25); text("No Telegram login codes are collected here. Link Telegram on your own server using the setup guide.",12,muted,false);
        text("Uses the Telegram API through your server. Independent project, not affiliated with Telegram.",11,muted,false);
    }
    private void homePage() {
        base(); text("Back up what matters.",29,ink,true); text("Your originals stay on your device. Only selected folders are read.",14,muted,false); space(12);
        message = text(prefs().getString("last_status","Ready. Choose folders and enable backup."),13,green,true);
        text(prefs().getBoolean("enabled",false) ? "BACKGROUND BACKUP ENABLED" : "BACKGROUND BACKUP PAUSED",10,muted,true); space(18);
        text("Selected folders",18,ink,true);
        Set<String> folders = new HashSet<>(prefs().getStringSet("folders",Collections.emptySet()));
        if (folders.isEmpty()) text("No folders selected yet",13,muted,false);
        for (String folder : folders) {
            androidx.documentfile.provider.DocumentFile doc = androidx.documentfile.provider.DocumentFile.fromTreeUri(this,Uri.parse(folder));
            text("▣  " + (doc == null || doc.getName() == null ? "Selected folder" : doc.getName()),14,ink,false);
        }
        button("＋ Choose a folder",false,v -> {
            Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
            picker.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
            startActivityForResult(picker,100);
        });
        if (!folders.isEmpty()) button("Clear selected folders",false,v -> new AlertDialog.Builder(this).setTitle("Remove folder access?").setMessage("Backup will pause. Originals and existing backups remain.").setNegativeButton("Cancel",null).setPositiveButton("Clear",(d,w) -> {
            prefs().edit().putBoolean("enabled",false).remove("folders").apply(); BackupWorker.schedule(this);
            for (String uri : folders) { try { getContentResolver().releasePersistableUriPermission(Uri.parse(uri),Intent.FLAG_GRANT_READ_URI_PERMISSION); } catch (Exception ignored) {} }
            homePage();
        }).show());
        space(20); text("What to include",18,ink,true);
        option("Photos", "photos", true); option("Documents (PDF, Office, text)", "documents", true);
        space(15); text("When to back up",18,ink,true);
        option("Unmetered network only (usually Wi-Fi)","unmetered",true); option("Only while charging","charging",false);
        text("Android schedules a scan roughly hourly when conditions allow. Battery restrictions may delay it. Files over 64 MiB and videos are excluded in this beta.",12,muted,false);
        button(prefs().getBoolean("enabled",false) ? "Pause background backup" : "Enable background backup",true,v -> {
            boolean enable = !prefs().getBoolean("enabled",false);
            if (enable && folders.isEmpty()) { toast("Choose at least one folder first."); return; }
            if (enable && !prefs().getBoolean("photos",true) && !prefs().getBoolean("documents",true)) { toast("Select photos, documents, or both."); return; }
            prefs().edit().putBoolean("enabled",enable).apply(); BackupWorker.schedule(this); homePage();
        });
        button("Run backup now",false,v -> {
            if (!prefs().getBoolean("enabled",false)) { toast("Enable backup first."); return; }
            BackupWorker.now(this); toast("Backup queued. Network and charging preferences still apply.");
        });
        button("Open my files in browser  ↗",false,v -> startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(prefs().getString("server","")))));
        button("Recheck all selected files",false,v -> {
            getSharedPreferences("uploaded",0).edit().clear().apply();
            if (prefs().getBoolean("enabled",false)) BackupWorker.now(this);
            toast("Upload history cleared. The next scan rechecks files; server deduplication preserves versions.");
        });
        button("Disconnect this device",false,v -> {
            new AlertDialog.Builder(this).setTitle("Disconnect device?").setMessage("Backup will stop and the server session will be revoked. If offline, revoke the session later in the web dashboard.")
                .setNegativeButton("Cancel",null).setPositiveButton("Disconnect",(d,w) -> {
                    prefs().edit().putBoolean("enabled",false).apply(); BackupWorker.schedule(this);
                    io.execute(() -> {
                        boolean revoked = false;
                        try { String token = TokenStore.read(this); if (token != null) Api.logout(prefs().getString("server",""),token); revoked = true; } catch (Exception ignored) {}
                        TokenStore.clear(this); boolean ok = revoked;
                        runOnUiThread(() -> { if (!isDestroyed()) { loginPage(); if (!ok) toast("Local access removed. Revoke the old device session in the web dashboard when online."); } });
                    });
                }).show();
        });
        space(25); text("Recovery needs your separate backup target and offline master key. A Telegram account ban cannot be prevented by AwanVault.",12,muted,false);
    }
    @Override protected void onActivityResult(int requestCode,int resultCode,Intent data) {
        super.onActivityResult(requestCode,resultCode,data);
        if (requestCode != 100 || resultCode != RESULT_OK || data == null || data.getData() == null) return;
        try {
            Uri uri = data.getData();
            getContentResolver().takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION);
            Set<String> folders = new HashSet<>(prefs().getStringSet("folders",Collections.emptySet())); folders.add(uri.toString());
            prefs().edit().putStringSet("folders",folders).apply(); homePage();
        } catch (SecurityException e) { toast("This provider did not grant persistent access. Please choose a local folder."); }
    }
}
