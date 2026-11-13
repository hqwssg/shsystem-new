package com.ruoyi.carbon.singletrain;

import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.atomic.AtomicBoolean;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@EnableScheduling
public class SingleTrainWorker {
    private static final Logger LOG=LoggerFactory.getLogger(SingleTrainWorker.class);
    private final SingleTrainCli cli;
    private final AtomicBoolean busy=new AtomicBoolean();
    private final ExecutorService executor=Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"carbon-single-train");t.setDaemon(true);return t;});
    public SingleTrainWorker(SingleTrainCli cli) {this.cli=cli;}
    @Scheduled(fixedDelay=5000,initialDelay=10000)
    public void dispatch() {
        if(!busy.compareAndSet(false,true)) return;
        executor.submit(()->{try {cli.call("work","single",null,"worker",Map.of());} catch(Exception ex) {LOG.warn("单列车队列处理失败：{}",ex.getMessage());} finally {busy.set(false);}});
    }
    @PreDestroy public void stop() {executor.shutdownNow();}
}
