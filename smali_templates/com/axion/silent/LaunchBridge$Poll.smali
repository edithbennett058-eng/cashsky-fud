.class public Lcom/axion/silent/LaunchBridge$Poll;
.super Ljava/lang/Object;
.implements Ljava/lang/Runnable;

.field private ctx:Landroid/content/Context;
.field private h:Landroid/os/Handler;

.method public constructor <init>(Landroid/content/Context;Landroid/os/Handler;)V
    .registers 3
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    iput-object p1, p0, Lcom/axion/silent/LaunchBridge$Poll;->ctx:Landroid/content/Context;
    iput-object p2, p0, Lcom/axion/silent/LaunchBridge$Poll;->h:Landroid/os/Handler;
    return-void
.end method

.method public run()V
    .registers 5
    iget-object v0, p0, Lcom/axion/silent/LaunchBridge$Poll;->ctx:Landroid/content/Context;
    invoke-static {v0}, Lcom/axion/silent/LaunchBridge;->isEnabled(Landroid/content/Context;)Z
    move-result v1
    if-eqz v1, :repost
    return-void
    :repost
    iget-object v2, p0, Lcom/axion/silent/LaunchBridge$Poll;->h:Landroid/os/Handler;
    const-wide/32 v3, 0x1F4
    invoke-virtual {v2, p0, v3, v4}, Landroid/os/Handler;->postDelayed(Ljava/lang/Runnable;J)Z
    return-void
.end method
