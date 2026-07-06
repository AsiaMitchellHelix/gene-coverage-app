resource "aws_ses_email_identity" "sender" {
  email = var.ses_sender_email
}

resource "aws_iam_policy" "ses_send" {
  name = "${var.app_name}-ses-send"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ses:SendEmail", "ses:SendRawEmail"]
      Resource = aws_ses_email_identity.sender.arn
    }]
  })
}
