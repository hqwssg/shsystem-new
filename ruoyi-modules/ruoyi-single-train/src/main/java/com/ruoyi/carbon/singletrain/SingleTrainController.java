package com.ruoyi.carbon.singletrain;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import org.springframework.core.io.InputStreamResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.common.core.web.controller.BaseController;
import com.ruoyi.common.core.web.domain.AjaxResult;
import com.ruoyi.common.security.annotation.RequiresPermissions;
import com.ruoyi.common.security.utils.SecurityUtils;
import com.ruoyi.common.log.annotation.Log;
import com.ruoyi.common.log.enums.BusinessType;

@RestController
@RequestMapping("/carbon/single-train")
public class SingleTrainController extends BaseController {
    private final SingleTrainCli cli;
    public SingleTrainController(SingleTrainCli cli) {this.cli=cli;}
    static Long dept() {return SecurityUtils.isAdmin()?null:SecurityUtils.getLoginUser().getSysUser().getDeptId();}
    Object call(String action,Object body) {return cli.call(action,"single",dept(),SecurityUtils.getUsername(),body);}
    @GetMapping("/versions") @RequiresPermissions("carbon:singleTrain:query") public AjaxResult versions(){return success(call("versions",Map.of()));}
    @GetMapping("/sources") @RequiresPermissions("carbon:singleTrain:version") public AjaxResult sources(){return success(call("sources",Map.of()));}
    @PostMapping("/sources/preview") @RequiresPermissions("carbon:singleTrain:version") public AjaxResult preview(@RequestBody Map<String,Object> body){return success(call("preview",body));}
    @PostMapping("/versions") @RequiresPermissions("carbon:singleTrain:version") @Log(title="单列车基础数据派生",businessType=BusinessType.INSERT)
    public AjaxResult derive(@RequestBody Map<String,Object> body){return success(call("derive",body));}
    @GetMapping("/versions/{id}") @RequiresPermissions("carbon:singleTrain:query") public AjaxResult version(@PathVariable String id){return success(call("version",Map.of("id",id)));}
    @PutMapping("/versions/{id}") @RequiresPermissions("carbon:singleTrain:version") @Log(title="单列车草稿维护",businessType=BusinessType.UPDATE)
    public AjaxResult save(@PathVariable String id,@RequestBody Map<String,Object> body){body.put("id",id);return success(call("save",body));}
    @PostMapping("/versions/{id}/defaults") @RequiresPermissions("carbon:singleTrain:version") public AjaxResult defaults(@PathVariable String id){return success(call("defaults",Map.of("id",id)));}
    @PostMapping("/versions/{id}/publish") @RequiresPermissions("carbon:singleTrain:version") @Log(title="单列车版本发布",businessType=BusinessType.INSERT)
    public AjaxResult publish(@PathVariable String id){return success(call("publish",Map.of("id",id)));}
    @PostMapping("/versions/{id}/files") @RequiresPermissions("carbon:singleTrain:version") public AjaxResult upload(@PathVariable String id,@RequestParam("files") List<MultipartFile> files,@RequestParam(value="relativePaths",required=false) List<String> names) throws Exception {return success(uploadFiles(cli,"single",id,files,names));}
    static Object uploadFiles(SingleTrainCli cli,String target,String id,List<MultipartFile> files,List<String> names) throws Exception {
        // Authorize the draft before writing any uploaded content.
        cli.call("version",target,dept(),SecurityUtils.getUsername(),Map.of("id",id));
        List<Path> staged=new ArrayList<>();List<Map<String,String>> uploads=new ArrayList<>();
        try {
            Path dir=cli.workspace().resolve("output/single_train_uploads");Files.createDirectories(dir);
            long total=0;
            for(int i=0;i<files.size();i++) {
                MultipartFile file=files.get(i);total+=file.getSize();if(total>64L*1024*1024) throw new IllegalArgumentException("文件超过64MB");
                String name=names!=null&&i<names.size()?names.get(i):file.getOriginalFilename();
                if(name==null||name.contains("..")||name.contains(":")||name.startsWith("/")||name.startsWith("\\"))throw new IllegalArgumentException("文件名不安全");
                String suffix=name.toLowerCase(Locale.ROOT).endsWith(".xlsx")?".xlsx":".data";
                Path p=Files.createTempFile(dir,"upload-",suffix);staged.add(p);file.transferTo(p);uploads.add(Map.of("name",name,"localPath",p.toString()));
            }
            return cli.call("upload",target,dept(),SecurityUtils.getUsername(),Map.of("id",id,"uploads",uploads));
        } finally {for(Path p:staged) Files.deleteIfExists(p);}
    }
    @GetMapping("/parameter-preset") @RequiresPermissions("carbon:singleTrain:query") public AjaxResult preset(@RequestParam String versionId){return success(call("preset",Map.of("id",versionId)));}
    @GetMapping("/runs") @RequiresPermissions("carbon:singleTrain:list") public AjaxResult runs(){return success(call("runs",Map.of()));}
    @PostMapping("/runs") @RequiresPermissions("carbon:singleTrain:run") @Log(title="单列车能量任务",businessType=BusinessType.INSERT)
    public AjaxResult create(@RequestBody Map<String,Object> body){return success(call("create-run",body));}
    @GetMapping("/runs/{id}") @RequiresPermissions("carbon:singleTrain:query") public AjaxResult run(@PathVariable String id){return success(call("run",Map.of("id",id)));}
    @PostMapping("/runs/{id}/cancel") @RequiresPermissions("carbon:singleTrain:cancel") public AjaxResult cancel(@PathVariable String id){return success(call("cancel",Map.of("id",id)));}
    @GetMapping("/cases/{id}/trace") @RequiresPermissions("carbon:singleTrain:query") public AjaxResult trace(@PathVariable String id){return success(call("trace",Map.of("id",id)));}
    @GetMapping("/artifacts/{id}") @RequiresPermissions("carbon:singleTrain:download") public ResponseEntity<InputStreamResource> artifact(@PathVariable String id) throws Exception {
        JSONObject a=(JSONObject)call("artifact",Map.of("id",id));Path file=Path.of(a.getString("localPath")).toAbsolutePath().normalize();
        if(!file.startsWith(cli.resultRoot())||!Files.isRegularFile(file))throw new IllegalArgumentException("结果文件路径不合法");
        String name=URLEncoder.encode(file.getFileName().toString(),StandardCharsets.UTF_8);
        return ResponseEntity.ok().header(HttpHeaders.CONTENT_DISPOSITION,"attachment; filename*=UTF-8''"+name).contentLength(Files.size(file)).body(new InputStreamResource(Files.newInputStream(file)));
    }
}
