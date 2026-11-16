import { useEffect, useState } from 'react'
import { Alert, Card, Col, Row, Select, Space, Spin, Statistic, Table, Tag, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api, AnalysisRun } from '../api'
import { Loading, useProject } from '../projectContext'
import { runTypeLabel, statusLabel } from '../locales/zh-CN'

const { Title, Text } = Typography

const reliabilityExperiments = [
  { id: 'Exp006', title: '候选排名可靠性', summary: '固定药物条件比较方案 A/B、剂量稳定性与 QC 门槛；报告指出 Top10 成员对方案选择仍较敏感。', metric: 'A/B 排名 Spearman 0.894 · Top10 重合 4/10', href: '/reliability/Exp006.md' },
  { id: 'Exp007', title: '疾病签名规模敏感性', summary: '在相同 4,761 条历史 LINCS 签名上改变 S1 基因名单规模，并核验历史 WTCS 可复现。', metric: '28,566 条签名级评分 · 22,290 条条件结果', href: '/reliability/Exp007.md' },
  { id: 'Exp008', title: '评分方法与随机对照', summary: '对照多个表达连接评分方法，并用同大小随机 BING 基因集估计经验零分布。', metric: '2,000 次随机查询 · B200 有 760/3,715 条条件 q<0.05', href: '/reliability/Exp008.md' },
  { id: 'Exp009', title: 'LINCS 质量与剂量敏感性', summary: '检查重复一致性、TAS 字段和不同 QC 阈值的影响；剂量条件分开保留。', metric: '11,850 条 24 h 可评分签名', href: '/reliability/Exp009.md' },
  { id: 'Exp010', title: '独立患者队列验证', summary: '使用独立 GSE139038 队列核查疾病表达方向与药物排名；配对样本量有限，定位为外部复核。', metric: '14 对 ER 阳性肿瘤/正常样本', href: '/reliability/Exp010.md' },
  { id: 'Exp011', title: 'PRISM 体外敏感性对照', summary: '将 S2 候选与 PRISM 药物敏感性按化学结构严格匹配；体外细胞活力不等同临床获益。', metric: 'Top50 中 37 个通过结构标识匹配', href: '/reliability/Exp011.md' },
]

export default function RunComparisonPage() {
  const { project } = useProject()
  const runs = useQuery({queryKey:['project-runs',project?.project_id],queryFn:()=>api.runs(project!.project_id),enabled:!!project})
  const [runAId,setRunAId]=useState<string>()
  const [runBId,setRunBId]=useState<string>()
  const eligible=(runs.data??[]).filter(run=>run.status==='completed')
  const runA=eligible.find(run=>run.analysis_run_id===runAId)
  const sameTypeRuns=runA?eligible.filter(run=>run.run_type===runA.run_type):[]
  useEffect(()=>{
    if(!eligible.some(run=>run.analysis_run_id===runAId)){
      const first=eligible.find(run=>eligible.some(other=>other.run_type===run.run_type&&other.analysis_run_id!==run.analysis_run_id))??eligible[0]
      setRunAId(first?.analysis_run_id)
      setRunBId(first?sameTypeAlternative(eligible,first)?.analysis_run_id:undefined)
    }
  },[runs.data,project?.project_id])
  useEffect(()=>{
    if(!runA){setRunBId(undefined);return}
    if(!sameTypeRuns.some(run=>run.analysis_run_id===runBId))setRunBId(sameTypeAlternative(sameTypeRuns,runA)?.analysis_run_id)
  },[runAId,runs.data])
  const comparison=useQuery({queryKey:['run-comparison',project?.project_id,runAId,runBId],queryFn:()=>api.compareRuns(project!.project_id,runAId!,runBId!),enabled:!!project&&!!runAId&&!!runBId&&runAId!==runBId&&runA?.run_type===eligible.find(run=>run.analysis_run_id===runBId)?.run_type})
  if(runs.isLoading)return <Loading/>
  if(runs.error)return <Loading error={runs.error as Error}/>
  const result=comparison.data
  const provenance=result?.provenance_comparison
  const output=result?.output_comparison
  const s2=output?.condition_matched_comparison as Record<string,unknown>|undefined
  const delta=s2?.wtcs_delta_run_b_minus_run_a as Record<string,unknown>|undefined
  const rankDelta=s2?.within_condition_rank_delta_run_b_minus_run_a as Record<string,unknown>|undefined
  const changedKeys=(provenance?.different_parameter_keys as string[]|undefined)??[]
  return <>
    <div className="page-heading"><div><Text className="eyebrow">Exp006–Exp011 · 可复现性与外部核验</Text><Title level={2}>可靠性分析</Title><Text type="secondary">查看已完成的稳定性、随机对照、独立队列和 PRISM 实验。各项检验回答不同问题，不等同于临床疗效验证。</Text></div><a className="toolbar-button" href="/final05-scientific-audit-report.md" download>查看 Final05 科研审计</a></div>
    <Row gutter={[14,14]} className="section-card">{reliabilityExperiments.map(item=><Col key={item.id} xs={24} md={12} xl={8}><Card className="experiment-card" title={<Space><Tag color="blue">{item.id}</Tag>{item.title}</Space>} extra={<Tag color="green">已生成报告</Tag>}><Text type="secondary">{item.summary}</Text><div className="experiment-metric">{item.metric}</div><a href={item.href} target="_blank" rel="noreferrer">阅读实验报告 →</a></Card></Col>)}</Row>
    <Alert className="section-card" type="info" showIcon message="结论解读边界" description="卡片摘要取自各 Exp 原始报告；详细参数、数据来源、局限和结果以报告及 experiments/ 下的结果文件为准。Exp006–011 分别评估排名/方法稳定性、疾病签名敏感性、统计对照、LINCS 质量、独立队列和 PRISM 细胞活力。" />
    <Card className="section-card" title="项目内分析运行版本比较"><Text type="secondary">只比较同一项目、同一分析类型的已完成版本；S2 仅匹配相同剂量、时间条件和 LINCS perturbagen。</Text><Space wrap style={{display:'flex',marginTop:14}}><Select showSearch optionFilterProp="label" value={runAId} placeholder="基准运行" style={{minWidth:360}} options={eligible.map(run=>({value:run.analysis_run_id,label:`${runTypeLabel(run.run_type)} · ${run.analysis_run_id}`}))} onChange={id=>{setRunAId(id);setRunBId(undefined)}}/><Select showSearch optionFilterProp="label" value={runBId} placeholder="比较运行（类型与基准一致）" style={{minWidth:360}} options={sameTypeRuns.filter(run=>run.analysis_run_id!==runAId).map(run=>({value:run.analysis_run_id,label:`${runTypeLabel(run.run_type)} · ${run.analysis_run_id}`}))} onChange={setRunBId}/></Space>{eligible.length<2&&<Alert style={{marginTop:12}} type="info" showIcon message="项目中还没有足够的已完成运行" description="完成同一种分析的第二个版本后，可在这里比较来源、参数和结果变化。"/>}{runA&&sameTypeRuns.length<2&&<Alert style={{marginTop:12}} type="info" showIcon message={`当前 ${runTypeLabel(runA.run_type)} 只有一个已完成版本`} description="其他分析类型不会混在一起比较。"/>}</Card>
    {comparison.isError&&<Alert type="error" showIcon message="运行比较失败" description={(comparison.error as Error).message} style={{marginBottom:12}}/>}
    {comparison.isLoading&&<Card className="section-card"><Spin/></Card>}
    {result&&<>
      <div className="stats-grid"><Card><Statistic title="运行类型" value={runTypeLabel(result.run_type)}/></Card><Card><Statistic title="输入哈希完全一致" value={String(provenance?.identical_input_hashes)}/></Card><Card><Statistic title="相同输入文件哈希数" value={Number(provenance?.shared_hash_keys??0)}/></Card><Card><Statistic title="参数差异项" value={changedKeys.length}/></Card></div>
      {s2&&<><Alert type="info" showIcon message="S2 匹配比较，不合并不同剂量或时间" description={String(s2.comparison_unit)}/><div className="stats-grid"><Card><Statistic title="两版共有的条件-药物行" value={Number(s2.shared_condition_perturbagen_rows??0)}/></Card><Card><Statistic title="B−A WTCS 中位变化" value={typeof delta?.median==='number'?Number(delta.median).toFixed(4):'—'}/></Card><Card><Statistic title="B−A WTCS 绝对变化中位数" value={typeof delta?.median_absolute==='number'?Number(delta.median_absolute).toFixed(4):'—'}/></Card><Card><Statistic title="B−A 条件内排名绝对变化中位数" value={typeof rankDelta?.median_absolute==='number'?Number(rankDelta.median_absolute).toFixed(2):'—'}/></Card></div><Card className="section-card" title="S2 条件匹配覆盖"><Table size="small" pagination={false} rowKey="metric" dataSource={[{metric:'仅在运行 A 中',value:s2.only_in_run_a},{metric:'仅在运行 B 中',value:s2.only_in_run_b},{metric:'WTCS 有效配对数',value:delta?.n},{metric:'排名有效配对数',value:rankDelta?.n}]} columns={[{title:'指标',dataIndex:'metric'},{title:'数量',dataIndex:'value'}]}/></Card></>}
      <Card className="section-card" title="参数变化"><Table size="small" pagination={false} rowKey="key" dataSource={changedKeys.map(key=>({key,a:JSON.stringify(result.run_a.parameters[key]??null),b:JSON.stringify(result.run_b.parameters[key]??null)}))} columns={[{title:'参数',dataIndex:'key'},{title:'运行 A',dataIndex:'a',render:(value:string)=><Text code>{value}</Text>},{title:'运行 B',dataIndex:'b',render:(value:string)=><Text code>{value}</Text>}]} locale={{emptyText:'参数一致'}}/></Card>
      <Card className="section-card" title="运行来源与输出摘要"><Space align="start" size="large" wrap>{[result.run_a,result.run_b].map((run,index)=><Card size="small" key={run.analysis_run_id} title={`${runTypeLabel(run.run_type)} · 运行 ${index===0?'A':'B'}`} style={{minWidth:360,maxWidth:560}}><Text type="secondary">{run.created_at} · {statusLabel(run.status)}</Text><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:380,overflow:'auto'}}>{JSON.stringify({software_versions:run.software_versions,input_hashes:run.input_hashes,output_summary:run.output_summary},null,2)}</pre></Card>)}</Space></Card>
    </>}
  </>
}

function sameTypeAlternative(runs:AnalysisRun[],reference:AnalysisRun) {
  return runs.find(run=>run.run_type===reference.run_type&&run.analysis_run_id!==reference.analysis_run_id)
}
