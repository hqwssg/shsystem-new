package com.ruoyi.carbon.singletrain;

import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import com.ruoyi.common.core.web.controller.BaseController;
import com.ruoyi.common.core.web.domain.AjaxResult;
import com.ruoyi.common.security.annotation.RequiresPermissions;
import com.ruoyi.common.security.utils.SecurityUtils;
import com.ruoyi.common.log.annotation.Log;
import com.ruoyi.common.log.enums.BusinessType;

@RestController @RequestMapping("/carbon/energy")
public class EnergySharedVersionController extends BaseController {
    private final SingleTrainCli cli;
    public EnergySharedVersionController(SingleTrainCli cli){this.cli=cli;}
    Object call(String action,Object body){return cli.call(action,"energy",SingleTrainController.dept(),SecurityUtils.getUsername(),body);}
    @GetMapping("/data-sources") @RequiresPermissions("carbon:energy:version") public AjaxResult sources(){return success(call("sources",Map.of()));}
    @PostMapping("/data-sources/preview") @RequiresPermissions("carbon:energy:version") public AjaxResult preview(@RequestBody Map<String,Object> body){return success(call("preview",body));}
    @GetMapping("/shared-versions") @RequiresPermissions("carbon:energy:version") public AjaxResult versions(){return success(call("versions",Map.of()));}
    @PostMapping("/shared-versions") @RequiresPermissions("carbon:energy:version") @Log(title="重空协同基础数据派生",businessType=BusinessType.INSERT) public AjaxResult derive(@RequestBody Map<String,Object> body){return success(call("derive",body));}
    @GetMapping("/shared-versions/{id}") @RequiresPermissions("carbon:energy:version") public AjaxResult version(@PathVariable String id){return success(call("version",Map.of("id",id)));}
    @PutMapping("/shared-versions/{id}") @RequiresPermissions("carbon:energy:version") public AjaxResult save(@PathVariable String id,@RequestBody Map<String,Object> body){body.put("id",id);return success(call("save",body));}
    @PostMapping("/shared-versions/{id}/publish") @RequiresPermissions("carbon:energy:version") @Log(title="重空协同复用版本发布",businessType=BusinessType.INSERT) public AjaxResult publish(@PathVariable String id){return success(call("publish",Map.of("id",id)));}
    @PostMapping("/shared-versions/{id}/files") @RequiresPermissions("carbon:energy:version") public AjaxResult upload(@PathVariable String id,@RequestParam("files") List<MultipartFile> files,@RequestParam(value="relativePaths",required=false) List<String> names) throws Exception {return success(SingleTrainController.uploadFiles(cli,"energy",id,files,names));}
}
