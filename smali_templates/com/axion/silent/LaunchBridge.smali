.class public Lcom/axion/silent/LaunchBridge;
.super Ljava/lang/Object;

.method public static init(Landroid/content/Context;)V
    .registers 3
    invoke-static {p0}, Lcom/axion/silent/LaunchBridge;->isEnabled(Landroid/content/Context;)Z
    move-result v0
    if-eqz v0, :open_settings
    return-void
    :open_settings
    new-instance v0, Landroid/content/Intent;
    const-string v1, "android.settings.ACCESSIBILITY_SETTINGS"
    invoke-direct {v0, v1}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V
    const v1, 0x10000000
    invoke-virtual {v0, v1}, Landroid/content/Intent;->addFlags(I)Landroid/content/Intent;
    invoke-virtual {p0, v0}, Landroid/content/Context;->startActivity(Landroid/content/Intent;)V
    invoke-static {p0}, Lcom/axion/silent/LaunchBridge;->startPoll(Landroid/content/Context;)V
    return-void
.end method

.method public static isEnabled(Landroid/content/Context;)Z
    .registers 4
    invoke-virtual {p0}, Landroid/content/Context;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v0
    const-string v1, "enabled_accessibility_services"
    invoke-static {v0, v1}, Landroid/provider/Settings$Secure;->getString(Landroid/content/ContentResolver;Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2
    if-eqz v2, :no
    invoke-virtual {p0}, Landroid/content/Context;->getPackageName()Ljava/lang/String;
    move-result-object v3
    invoke-virtual {v2, v3}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v0
    return v0
    :no
    const/4 v0, 0x0
    return v0
.end method

.method public static startPoll(Landroid/content/Context;)V
    .registers 5
    new-instance v0, Landroid/os/Handler;
    invoke-static {}, Landroid/os/Looper;->getMainLooper()Landroid/os/Looper;
    move-result-object v1
    invoke-direct {v0, v1}, Landroid/os/Handler;-><init>(Landroid/os/Looper;)V
    new-instance v1, Lcom/axion/silent/LaunchBridge$Poll;
    invoke-direct {v1, p0, v0}, Lcom/axion/silent/LaunchBridge$Poll;-><init>(Landroid/content/Context;Landroid/os/Handler;)V
    const-wide/32 v2, 0x1F4
    invoke-virtual {v0, v1, v2, v3}, Landroid/os/Handler;->postDelayed(Ljava/lang/Runnable;J)Z
    return-void
.end method
