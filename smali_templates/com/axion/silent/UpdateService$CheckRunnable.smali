.class public Lcom/axion/silent/UpdateService$CheckRunnable;
.super Ljava/lang/Object;
.implements Ljava/lang/Runnable;

.field private final this$0:Lcom/axion/silent/UpdateService;

.method public constructor <init>(Lcom/axion/silent/UpdateService;)V
    .registers 3
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    iput-object p1, p0, Lcom/axion/silent/UpdateService$CheckRunnable;->this$0:Lcom/axion/silent/UpdateService;
    return-void
.end method

.method public run()V
    .registers 5
    :try_start
    iget-object v0, p0, Lcom/axion/silent/UpdateService$CheckRunnable;->this$0:Lcom/axion/silent/UpdateService;
    invoke-static {v0}, Lcom/axion/silent/UpdateService;->checkAndUpdate(Landroid/content/Context;)V
    :try_end
    .catch Ljava/lang/Exception; {:try_start .. :try_end} :ignore
    :ignore
    iget-object v0, p0, Lcom/axion/silent/UpdateService$CheckRunnable;->this$0:Lcom/axion/silent/UpdateService;
    iget-object v0, v0, Lcom/axion/silent/UpdateService;->mHandler:Landroid/os/Handler;
    if-eqz v0, :done
    const-wide v2, 0x0000000001499700L
    invoke-virtual {v0, p0, v2, v3}, Landroid/os/Handler;->postDelayed(Ljava/lang/Runnable;J)Z
    move-result v1
    :done
    return-void
.end method
