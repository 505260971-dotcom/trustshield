import { InfoCircleOutlined } from '@ant-design/icons'
import { Space, Tag, Typography } from 'antd'
import { approvalRoleLabel } from './common'

const { Text } = Typography

export default function TaskContextBanner({
  role,
  title,
  description,
  nextAction,
}: {
  role?: string
  title: string
  description: string
  nextAction?: string
}) {
  return <div className="task-context-banner">
    <InfoCircleOutlined />
    <div>
      <Space wrap size={6}>
        {role && <Tag color="blue">{approvalRoleLabel(role)}</Tag>}
        <Text strong>{title}</Text>
      </Space>
      <Text type="secondary">{description}</Text>
      {nextAction && <Text className="task-context-next">下一步：{nextAction}</Text>}
    </div>
  </div>
}
