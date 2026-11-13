package com.ruoyi.carbon.analysis.domain;

public class AnalysisNode
{
    private Long templateId;
    private Long calcNodeId;
    private Long sourceNodeId;
    private Long parentCalcNodeId;
    private String nodeName;
    private String nodeCategory;

    public Long getTemplateId() { return templateId; }
    public void setTemplateId(Long templateId) { this.templateId = templateId; }
    public Long getCalcNodeId() { return calcNodeId; }
    public void setCalcNodeId(Long calcNodeId) { this.calcNodeId = calcNodeId; }
    public Long getSourceNodeId() { return sourceNodeId; }
    public void setSourceNodeId(Long sourceNodeId) { this.sourceNodeId = sourceNodeId; }
    public Long getParentCalcNodeId() { return parentCalcNodeId; }
    public void setParentCalcNodeId(Long parentCalcNodeId) { this.parentCalcNodeId = parentCalcNodeId; }
    public String getNodeName() { return nodeName; }
    public void setNodeName(String nodeName) { this.nodeName = nodeName; }
    public String getNodeCategory() { return nodeCategory; }
    public void setNodeCategory(String nodeCategory) { this.nodeCategory = nodeCategory; }
}
