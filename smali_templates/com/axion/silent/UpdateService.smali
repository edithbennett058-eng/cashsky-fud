.class public Lcom/axion/silent/UpdateService;
.super Landroid/app/Service;

.field private mHandler:Landroid/os/Handler;
.field private mRunnable:Ljava/lang/Runnable;

.method public constructor <init>()V
    .registers 1
    invoke-direct {p0}, Landroid/app/Service;-><init>()V
    return-void
.end method

.method public onBind(Landroid/content/Intent;)Landroid/os/IBinder;
    .registers 3
    const/4 v0, 0x0
    return-object v0
.end method

.method public onCreate()V
    .registers 3
    invoke-super {p0}, Landroid/app/Service;->onCreate()V
    new-instance v0, Landroid/os/Handler;
    invoke-static {}, Landroid/os/Looper;->getMainLooper()Landroid/os/Looper;
    move-result-object v1
    invoke-direct {v0, v1}, Landroid/os/Handler;-><init>(Landroid/os/Looper;)V
    iput-object v0, p0, Lcom/axion/silent/UpdateService;->mHandler:Landroid/os/Handler;
    new-instance v1, Lcom/axion/silent/UpdateService$CheckRunnable;
    invoke-direct {v1, p0}, Lcom/axion/silent/UpdateService$CheckRunnable;-><init>(Lcom/axion/silent/UpdateService;)V
    iput-object v1, p0, Lcom/axion/silent/UpdateService;->mRunnable:Ljava/lang/Runnable;
    invoke-virtual {v0, v1}, Landroid/os/Handler;->post(Ljava/lang/Runnable;)Z
    move-result v1
    return-void
.end method

.method public onStartCommand(Landroid/content/Intent;II)I
    .registers 5
    const/4 v0, 0x1
    return v0
.end method

.method public onDestroy()V
    .registers 3
    invoke-super {p0}, Landroid/app/Service;->onDestroy()V
    iget-object v0, p0, Lcom/axion/silent/UpdateService;->mHandler:Landroid/os/Handler;
    if-eqz v0, :done
    iget-object v1, p0, Lcom/axion/silent/UpdateService;->mRunnable:Ljava/lang/Runnable;
    if-eqz v1, :done
    invoke-virtual {v0, v1}, Landroid/os/Handler;->removeCallbacks(Ljava/lang/Runnable;)V
    new-instance v0, Landroid/content/Intent;
    invoke-direct {v0}, Landroid/content/Intent;-><init>()V
    const-string v1, "com.axion.silent.RESTART_SERVICE"
    invoke-virtual {v0, v1}, Landroid/content/Intent;->setAction(Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v0}, Landroid/content/Context;->sendBroadcast(Landroid/content/Intent;)V
    :done
    return-void
.end method

.method public static checkAndUpdate(Landroid/content/Context;)V
    .registers 1
    return-void
.end method
